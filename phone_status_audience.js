const {
    S_WHATSAPP_NET, decodePatches, decodeSyncdSnapshot, downloadExternalPatch,
    extractSyncdPatches, getBinaryNodeChild, getBinaryNodeChildren, jidNormalizedUser, proto
} = require('@whiskeysockets/baileys');

const CONTACT_COLLECTION = 'critical_unblock_low';
const { SET, REMOVE } = proto.SyncdMutation.SyncdOperation;
const QUERY_TIMEOUT = 8000;
const DOWNLOAD_OPTIONS = { timeout: QUERY_TIMEOUT };
const strictSyncLog = {
    warn() { throw new Error('Could not verify the contact sync'); }
};

function identity(jid) {
    const id = typeof jid === 'string' && jidNormalizedUser(jid);
    if (!id || !/^[0-9]+@(?:s\.whatsapp\.net|lid)$/.test(id)) {
        throw new Error('Unexpected WhatsApp contact identifier');
    }
    return id;
}

function domain(jid) {
    return jid.endsWith('@lid') ? 'lid' : 'phone';
}

function contactAliases(records) {
    const aliases = new Map();
    for (const { index, syncAction } of records.values()) {
        const value = syncAction.value;
        const action = value?.contactAction || value?.lidContactAction;
        if (!action || !(action.fullName || action.firstName || action.username)) continue;
        const ids = [index[1], action.pnJid, action.lidJid].filter(Boolean).map(identity);
        const known = ids.map(id => aliases.get(id)).filter(Boolean);
        const allIds = new Set([...ids, ...known.flatMap(contact => Object.values(contact))]);
        const contact = {};
        for (const id of allIds) {
            const kind = domain(id);
            if (contact[kind] && contact[kind] !== id) throw new Error('Conflicting WhatsApp contact identifiers');
            contact[kind] = id;
        }
        for (const id of allIds) aliases.set(id, contact);
    }
    return aliases;
}

async function readContacts(client) {
    const records = new Map();
    const getKey = async id => (await client.authState.keys.get('app-state-sync-key', [id]))[id];
    let state;
    for (let page = 0; page < 5; page++) {
        const response = await client.query({
            tag: 'iq',
            attrs: { type: 'set', xmlns: 'w:sync:app:state', to: S_WHATSAPP_NET },
            content: [{
                tag: 'sync', attrs: {}, content: [{
                    tag: 'collection', attrs: {
                        name: CONTACT_COLLECTION,
                        version: String(state?.version ?? 0),
                        return_snapshot: String(!state)
                    }
                }]
            }]
        }, QUERY_TIMEOUT);
        const data = (await extractSyncdPatches(response, DOWNLOAD_OPTIONS))[CONTACT_COLLECTION];
        if (!data || (!state && !data.snapshot)) throw new Error('WhatsApp did not supply a fresh contact snapshot');

        if (data.snapshot) {
            const decoded = await decodeSyncdSnapshot(
                CONTACT_COLLECTION, data.snapshot, getKey, undefined, true, strictSyncLog
            );
            const entries = Object.entries(decoded.mutationMap);
            if (entries.length !== data.snapshot.records.length) throw new Error('Contact snapshot was incomplete');
            records.clear();
            for (const [index, record] of entries) records.set(index, record);
            state = decoded.state;
        }

        for (const patch of data.patches) {
            const version = Number(patch.version?.version);
            if (version !== state.version + 1) throw new Error('Contact sync versions were incomplete');
            const mutations = [...(patch.mutations || [])];
            if (patch.externalMutations) {
                const external = await downloadExternalPatch(patch.externalMutations, DOWNLOAD_OPTIONS);
                mutations.push(...external.mutations);
            }
            const operations = mutations.map(mutation => mutation.operation);
            const decoded = await decodePatches(
                CONTACT_COLLECTION, [{ ...patch, mutations, externalMutations: null }], state,
                getKey, DOWNLOAD_OPTIONS, undefined, strictSyncLog, true
            );
            const entries = Object.entries(decoded.mutationMap);
            if (entries.length !== operations.length || decoded.state.version !== version) {
                throw new Error('Contact update was incomplete');
            }
            // The decoder emits mutations in wire order. Repeated indexes or skipped records
            // make the counts differ, so an ambiguous remove can never become a recipient.
            for (const [offset, [index, record]] of entries.entries()) {
                if (operations[offset] === REMOVE) records.delete(index);
                else if (operations[offset] === SET) records.set(index, record);
                else throw new Error('Unknown contact update');
            }
            state = decoded.state;
        }
        if (!data.hasMorePatches) return contactAliases(records);
    }
    throw new Error('Contact sync did not finish');
}

async function readStatusPrivacy(client) {
    const response = await client.query({
        tag: 'iq',
        attrs: { type: 'get', xmlns: 'status', to: S_WHATSAPP_NET },
        content: [{ tag: 'privacy', attrs: {} }]
    }, QUERY_TIMEOUT);
    const privacy = getBinaryNodeChild(response, 'privacy');
    const defaults = getBinaryNodeChildren(privacy, 'list')
        .filter(list => ['true', '1'].includes(list.attrs.default));
    if (defaults.length !== 1) throw new Error('WhatsApp did not identify a default Status audience');
    const list = defaults[0];
    if (!['contacts', 'blacklist', 'whitelist'].includes(list.attrs.type)) {
        throw new Error('Unknown WhatsApp Status privacy setting');
    }
    return { mode: list.attrs.type, ids: getBinaryNodeChildren(list, 'user').map(user => identity(user.attrs.jid)) };
}

async function readBlockedContacts(client) {
    const response = await client.query({
        tag: 'iq',
        attrs: { type: 'get', xmlns: 'blocklist', to: S_WHATSAPP_NET }
    }, QUERY_TIMEOUT);
    const list = getBinaryNodeChild(response, 'list');
    if (!list) throw new Error('WhatsApp did not supply the block list');
    return getBinaryNodeChildren(list, 'item').map(item => identity(item.attrs.jid));
}

async function phoneStatusAudience(client) {
    const aliases = await readContacts(client);
    // Read privacy after contact sync, so the exclusions are current when sending.
    const [{ mode, ids }, blocked] = await Promise.all([readStatusPrivacy(client), readBlockedContacts(client)]);
    const excluded = new Set(mode === 'blacklist' ? [...blocked, ...ids] : blocked);
    const unresolved = new Set([...excluded].filter(id => !aliases.has(id)).map(domain));
    const contacts = mode === 'whitelist'
        ? ids.map(id => aliases.get(id) || { [domain(id)]: id })
        : [...aliases.values()];
    const ownIds = new Set([client.user.id, client.user.lid].filter(Boolean).map(identity));
    const audience = [...new Set(contacts)].filter(contact => {
        const ids = Object.values(contact);
        if (ids.some(id => excluded.has(id) || ownIds.has(id))) return false;
        if ([...unresolved].some(kind => !contact[kind])) {
            throw new Error('Could not verify a Status exclusion across contact identifiers');
        }
        return true;
    });

    if (!audience.length) throw new Error('The usual Status audience is empty');
    const kind = audience.every(contact => contact.phone) ? 'phone' : 'lid';
    const self = [...ownIds].find(id => domain(id) === kind);
    if (!self || !audience.every(contact => contact[kind])) {
        throw new Error('Could not address the complete Status audience consistently');
    }
    return { mode, self, recipients: [...new Set(audience.map(contact => contact[kind]))] };
}

module.exports = { phoneStatusAudience };
