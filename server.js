require('dotenv').config();

// libsignal logs complete session objects through console, outside Baileys' logger.
const sessionLogs = new Set(['Closing session:', 'Opening session:', 'Removing old closed session:', 'Session already closed']);
for (const level of ['info', 'warn']) {
    const write = console[level].bind(console);
    console[level] = (message, ...args) => {
        if (!sessionLogs.has(message)) write(message, ...args);
    };
}

const {
    default: makeWASocket,
    DisconnectReason,
    generateMessageIDV2,
    jidNormalizedUser,
    useMultiFileAuthState,
    fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const QRCode = require('qrcode');
const qrcodeTerminal = require('qrcode-terminal');
const { youtubePage, youtubePreview } = require('./youtube_preview');
const { phoneStatusAudience } = require('./phone_status_audience');

const app = express();
app.use(bodyParser.json());

const PORT = Number(process.env.PORT || 5001);
const HOST = '127.0.0.1';
let sock = null;
let isConnected = false;
let qrCodeData = null;

async function startWhatsApp() {
    if (sock) {
        try { sock.end(); } catch (e) {}
    }
    const { state, saveCreds } = await useMultiFileAuthState('baileys_auth_info');
    
    // Fetch latest WhatsApp Web version to avoid 405 errors
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`using WA v${version.join('.')}, isLatest: ${isLatest}`);

    sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }), // Reduce log spam
        browser: ["Ubuntu", "Chrome", "110.0.5481.177"]
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (connection === 'close') {
            isConnected = false;
            const statusCode = lastDisconnect.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            
            console.log(`Connection closed (status ${statusCode}). Error:`, lastDisconnect.error?.message || lastDisconnect.error);
            
            if (shouldReconnect) {
                if (statusCode === DisconnectReason.connectionReplaced) {
                    console.log('⚠️ Connection Replaced (Conflict). Another instance might be running.');
                    console.log('Waiting 1 minute before attempting to reconnect to avoid loops...');
                    setTimeout(startWhatsApp, 60000);
                } else {
                    console.log('Reconnecting...');
                    startWhatsApp();
                }
            } else {
                console.log('Logged out. Delete baileys_auth_info folder to scan QR code again.');
            }
        } else if (connection === 'open') {
            isConnected = true;
            console.log('Opened connection, fully authenticated!');
            // Delete QR code file on successful connection
            if (fs.existsSync('qr_code.png')) {
                fs.unlinkSync('qr_code.png');
            }
        } else if (qr) {
            qrCodeData = qr;
            console.log('\n═══════════════════════════════════════════════════════════');
            console.log('  SCAN THIS QR CODE WITH WHATSAPP');
            console.log('  (WhatsApp → Settings → Linked Devices → Link a Device)');
            console.log('═══════════════════════════════════════════════════════════\n');
            qrcodeTerminal.generate(qr, { small: true });
            console.log('\n  If the code is unreadable in this terminal, also available at:');
            console.log('    • http://127.0.0.1:' + PORT + '/qr_code.png');
            console.log('    • qr_code.png (in the project folder)');
            console.log('    • your email / Telegram (if configured)\n');
            QRCode.toFile('qr_code.png', qr, {
                width: 512,
                margin: 2
            }, (err) => {
                if (err) console.error('Error saving QR code:', err);
            });
        }
    });

    sock.ev.on('creds.update', saveCreds);
}

startWhatsApp();

/**
 * Format the JID: Add @s.whatsapp.net for numbers and @g.us for groups.
 */
function formatContactId(contact) {
    if (contact.includes('@')) return contact; // Already a valid JID
    
    // Assume if it has largely letters or starts with multiple numbers and has a dash, it might be a group ID missing @g.us
    if (contact.includes('-')) {
        return contact + '@g.us';
    }
    
    // Clean phone numbers
    const numeric = contact.replace(/[^0-9]/g, '');
    return numeric + '@s.whatsapp.net';
}

async function textContent(client, text) {
    let linkPreview = null;
    try {
        linkPreview = await youtubePreview(text, client.waUploadToServer);
    } catch (error) {
        console.warn('YouTube preview unavailable:', error.name);
    }
    return { text, linkPreview };
}

// HTTP API endpoints

app.post('/send_message', async (req, res) => {
    let { contact, message } = req.body;
    if (typeof contact !== 'string' || !contact || typeof message !== 'string' || !message) {
        return res.status(400).json({ success: false, message: 'Missing contact or message' });
    }

    const jid = formatContactId(contact);
    try {
        if (!sock || !isConnected) {
            return res.status(503).json({ success: false, message: 'Driver not ready' });
        }
        
        console.log(`Sending message to ${jid}`);
        const client = sock;
        await client.sendMessage(jid, await textContent(client, message));
        res.json({ success: true, chatId: jid });
    } catch (e) {
        console.error(e);
        res.status(500).json({ success: false, error: String(e), chatId: jid });
    }
});

app.post('/post_status', async (req, res) => {
    const { link, audience } = req.body || {};
    const usePhoneAudience = audience === 'phone';
    if (typeof link !== 'string' || !link.startsWith('https://') ||
        /[\s<>"\x00-\x1f]/.test(link) || !youtubePage(link)) {
        return res.status(400).json({ success: false, message: 'Enter one HTTPS YouTube video or livestream link.' });
    }
    if (!usePhoneAudience && (!Array.isArray(audience) || audience.length < 1 || audience.length > 50 ||
        audience.some(number => typeof number !== 'string' || !/^\+[1-9][0-9]{6,14}$/.test(number)))) {
        return res.status(400).json({ success: false, message: 'Choose 1–50 viewers using international numbers.' });
    }
    const client = sock;
    if (!client || !isConnected) {
        return res.status(503).json({ success: false, message: 'Driver not ready' });
    }

    try {
        const content = await textContent(client, link);
        let recipients;
        let self;
        if (usePhoneAudience) {
            try {
                ({ recipients, self } = await phoneStatusAudience(client));
            } catch (error) {
                console.warn('Could not resolve the usual WhatsApp Status audience:', error.name);
                return res.status(422).json({
                    success: false,
                    message: 'Could not verify your usual Status audience. No Status was posted.'
                });
            }
        } else {
            recipients = [...new Set(audience.map(number => number.slice(1) + '@s.whatsapp.net'))];
            const contacts = await client.onWhatsApp(...recipients);
            const registered = new Set((contacts || []).filter(item => item.exists)
                .map(item => jidNormalizedUser(item.jid)));
            if (recipients.some(jid => !registered.has(jid))) {
                return res.status(422).json({ success: false, message: 'Check the viewer list. WhatsApp could not confirm every number.' });
            }
            self = jidNormalizedUser(client.user.id);
        }

        const messageId = generateMessageIDV2(client.user.id);
        const [ack] = await Promise.all([
            client.waitForMessage(messageId, usePhoneAudience ? 45000 : 30000),
            client.sendMessage('status@broadcast', content, {
                messageId,
                statusJidList: [...new Set([...recipients, self])],
                broadcast: true,
                backgroundColor: '#17324D'
            })
        ]);
        if (ack?.tag !== 'ack' || ack.attrs?.error) {
            return res.status(502).json({
                success: false,
                message: 'WhatsApp did not confirm the Status post. Check Status before trying again.'
            });
        }
        return res.json({ success: true });
    } catch (error) {
        console.error('WhatsApp Status post failed:', error.name);
        return res.status(502).json({
            success: false,
            message: 'WhatsApp could not confirm the Status post. Check Status before trying again.'
        });
    }
});

app.post('/send_poll', async (req, res) => {
    let { contact, question, options, allowMultiSelect } = req.body;
    
    if (!contact || !question || !options || !Array.isArray(options)) {
        return res.status(400).json({ success: false, message: 'Missing parameters for poll' });
    }

    const jid = formatContactId(contact);
    try {
        if (!sock || !isConnected) {
            return res.status(503).json({ success: false, message: 'Driver not ready' });
        }

        console.log(`Sending poll to ${jid}`);
        await sock.sendMessage(jid, {
            poll: {
                name: question,
                values: options,
                selectableCount: allowMultiSelect ? 0 : 1
            }
        });

        res.json({ success: true, chatId: jid });
    } catch (e) {
        console.error(e);
        res.status(500).json({ success: false, error: String(e), chatId: jid });
    }
});

app.get('/get_groups', async (req, res) => {
    try {
        if (!sock || !isConnected) {
            return res.status(503).json({ success: false, message: 'Driver not ready' });
        }

        // Fetch all groups from Baileys
        const groupData = await sock.groupFetchAllParticipating();
        const groups = Object.values(groupData).map(group => ({
            id: group.id,
            name: group.subject
        }));

        res.json({ success: true, groups });
    } catch (e) {
        console.error(e);
        res.status(500).json({ success: false, error: String(e) });
    }
});

app.get('/status', (req, res) => {
    res.json({
        ready: isConnected,
        status: isConnected ? "RUNNING_BAILEYS" : "STARTING"
    });
});

app.get('/qr_code.png', (req, res) => {
    const qrPath = path.join(__dirname || process.cwd(), 'qr_code.png');
    if (fs.existsSync(qrPath)) {
        res.sendFile(qrPath);
    } else {
        res.status(404).json({ success: false, message: 'QR code not available' });
    }
});

app.listen(PORT, HOST, () => {
    console.log(`Baileys Driver listening on ${HOST}:${PORT}`);
});
