import wa from '@open-wa/wa-automate';
const client = await wa.create({
  sessionId: 'whatsapp_scheduler', sessionDataPath: './', headless: true,
  multiDevice: false, useChrome: true, executablePath: '/usr/bin/chromium-browser',
  chromiumArgs: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  logConsole: false
});
const chats = await client.getAllChats();
const groups = chats.filter(c => c.isGroup);
console.log('Group Name -> JID mapping:');
groups.forEach(g => console.log(`  "${g.name}" => ${g.id}`));
await client.close();
