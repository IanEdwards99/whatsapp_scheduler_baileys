const { default: makeWASocket, DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const bodyParser = require('body-parser');

const app = express();
app.use(bodyParser.json());

const PORT = process.env.PORT || 5002;
let sock = null;
let isConnected = false;

async function startWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('baileys_auth_info');

    sock = makeWASocket({
        auth: state,
        logger: pino({ level: 'silent' }), // Reduce log spam
        printQRInTerminal: true
    });

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (connection === 'close') {
            isConnected = false;
            const shouldReconnect = lastDisconnect.error?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('Connection closed due to ', lastDisconnect.error, ', reconnecting ', shouldReconnect);
            if (shouldReconnect) {
                startWhatsApp();
            } else {
                console.log('Logged out. Delete baileys_auth_info folder to scan QR code again.');
            }
        } else if (connection === 'open') {
            isConnected = true;
            console.log('Opened connection, fully authenticated!');
        } else if (qr) {
            console.log('QR Code received, please scan it with your WhatsApp app.');
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

// Emulate open-wa driver endpoints

app.post('/send_message', async (req, res) => {
    try {
        if (!sock || !isConnected) {
            return res.status(503).json({ success: false, message: 'Driver not ready' });
        }
        
        let { contact, message } = req.body;
        if (!contact || !message) {
            return res.status(400).json({ success: false, message: 'Missing contact or message' });
        }

        const jid = formatContactId(contact);
        console.log(`Sending message to ${jid}`);
        
        await sock.sendMessage(jid, { text: message });
        
        res.json({ success: true, chatId: jid });
    } catch (e) {
        console.error(e);
        res.status(500).json({ success: false, error: String(e) });
    }
});

app.post('/send_poll', async (req, res) => {
    try {
        if (!sock || !isConnected) {
            return res.status(503).json({ success: false, message: 'Driver not ready' });
        }

        let { contact, question, options, allowMultiSelect } = req.body;
        
        if (!contact || !question || !options || !Array.isArray(options)) {
            return res.status(400).json({ success: false, message: 'Missing parameters for poll' });
        }

        const jid = formatContactId(contact);
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
        res.status(500).json({ success: false, error: String(e) });
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

app.listen(PORT, () => {
    console.log(`Baileys Driver started on port ${PORT}`);
});
