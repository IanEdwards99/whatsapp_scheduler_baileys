require('dotenv').config();

const {
    default: makeWASocket,
    DisconnectReason,
    useMultiFileAuthState,
    fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const QRCode = require('qrcode');

const app = express();
app.use(bodyParser.json());

const PORT = process.env.PORT || 5001;
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
            console.log('QR Code received, saving to qr_code.png');
            QRCode.toFile('qr_code.png', qr, {
                width: 512,
                margin: 2
            }, (err) => {
                if (err) console.error('Error saving QR code:', err);
                else console.log('QR code saved as qr_code.png');
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

// HTTP API endpoints

app.post('/send_message', async (req, res) => {
    let { contact, message } = req.body;
    if (!contact || !message) {
        return res.status(400).json({ success: false, message: 'Missing contact or message' });
    }

    const jid = formatContactId(contact);
    try {
        if (!sock || !isConnected) {
            return res.status(503).json({ success: false, message: 'Driver not ready' });
        }
        
        console.log(`Sending message to ${jid}`);
        await sock.sendMessage(jid, { text: message });
        res.json({ success: true, chatId: jid });
    } catch (e) {
        console.error(e);
        res.status(500).json({ success: false, error: String(e), chatId: jid });
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

app.listen(PORT, () => {
    console.log(`Baileys Driver started on port ${PORT}`);
});
