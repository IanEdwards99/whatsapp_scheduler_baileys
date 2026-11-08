const { setTimeout: delay } = require('node:timers/promises');
const { extractImageThumb, prepareWAMessageMedia } = require('@whiskeysockets/baileys');

const VIDEO_ID = /^[\w-]{11}$/;
const YOUTUBE_HOSTS = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be']);
const IMAGE_HOSTS = new Set([
    'i.ytimg.com', 'i1.ytimg.com', 'i2.ytimg.com', 'i3.ytimg.com', 'i4.ytimg.com',
    'img.youtube.com', 'yt3.ggpht.com', 'yt3.googleusercontent.com'
]);

function allowedUrl(value, hosts) {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.port || url.username || url.password || !hosts.has(url.hostname)) {
        throw new Error('Unexpected YouTube preview URL');
    }
    return url;
}

function findYouTubeLink(text) {
    const urls = text.match(/(?:https?:\/\/|www\.)[^\s<>"']+/gi) || [];
    for (const raw of urls) {
        const matched = raw.replace(/[.,!?:;)\]}]+$/, '');
        let source;
        try {
            source = new URL(/^www\./i.test(matched) ? 'https://' + matched : matched);
        } catch {
            continue;
        }
        if (!YOUTUBE_HOSTS.has(source.hostname) || source.port || source.username || source.password) {
            continue;
        }
        const parts = source.pathname.split('/').filter(Boolean);
        const video = source.hostname === 'youtu.be' ? parts[0] :
            parts[0] === 'watch' ? source.searchParams.get('v') :
            ['live', 'shorts', 'embed'].includes(parts[0]) ? parts[1] : '';
        if (video && VIDEO_ID.test(video)) {
            return { matched, page: 'https://www.youtube.com/watch?v=' + video };
        }
        if (source.hostname !== 'youtu.be' &&
            (/^\/@[^/]+\/live\/?$/.test(source.pathname) ||
             /^\/(?:channel|c|user)\/[^/]+\/live\/?$/.test(source.pathname))) {
            return { matched, page: 'https://www.youtube.com' + source.pathname };
        }
    }
}

async function getBytes(value, hosts, maxBytes, signal) {
    let url = allowedUrl(value, hosts);
    for (let redirect = 0; redirect <= 2; redirect++) {
        const response = await fetch(url, {
            redirect: 'manual',
            signal,
            // Request the page without optional cookies on YouTube's EU consent screen.
            headers: hosts === YOUTUBE_HOSTS ? { Cookie: 'SOCS=CAI' } : undefined
        });
        if (response.status >= 300 && response.status < 400) {
            await response.body?.cancel();
            const next = response.headers.get('location');
            if (!next) throw new Error('Missing preview redirect');
            url = allowedUrl(new URL(next, url), hosts);
            continue;
        }
        if (!response.ok) {
            await response.body?.cancel();
            throw new Error('YouTube preview HTTP ' + response.status);
        }
        const chunks = [];
        let size = 0;
        for await (const chunk of response.body) {
            size += chunk.length;
            if (size > maxBytes) throw new Error('YouTube preview exceeds size limit');
            chunks.push(chunk);
        }
        return Buffer.concat(chunks);
    }
    throw new Error('Too many preview redirects');
}

function openGraph(html) {
    const entities = { amp: '&', quot: '"', apos: "'", lt: '<', gt: '>' };
    const fields = {};
    for (const tag of html.matchAll(/<meta\s+(?:[^>"']|"[^"]*"|'[^']*')*>/gi)) {
        const attrs = Object.fromEntries(Array.from(
            tag[0].matchAll(/([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g),
            ([, name, double, single]) => [name.toLowerCase(), double ?? single]
        ));
        if (['og:title', 'og:description', 'og:image'].includes(attrs.property) &&
            attrs.content && !(attrs.property in fields)) {
            fields[attrs.property] = attrs.content.replace(/&(#x[\da-f]+|#\d+|\w+);/gi, (entity, key) => {
                if (key[0] !== '#') return Object.hasOwn(entities, key) ? entities[key] : entity;
                const code = key[1].toLowerCase() === 'x' ? parseInt(key.slice(2), 16) : Number(key.slice(1));
                return code <= 0x10ffff ? String.fromCodePoint(code) : entity;
            });
        }
    }
    return fields;
}

async function youtubePreview(text, upload) {
    const link = findYouTubeLink(text);
    if (!link) return null;
    const signal = AbortSignal.timeout(6000);
    const html = await getBytes(link.page, YOUTUBE_HOSTS, 4 * 1024 * 1024, signal);
    const metadata = openGraph(html.toString('utf8'));
    if (!metadata['og:title']) return null;
    const preview = {
        'canonical-url': link.page,
        'matched-text': link.matched,
        title: metadata['og:title'].slice(0, 200),
        description: (metadata['og:description'] || '').slice(0, 250)
    };
    if (!metadata['og:image']) return preview;
    try {
        const image = await getBytes(metadata['og:image'], IMAGE_HOSTS, 2 * 1024 * 1024, signal);
        preview.jpegThumbnail = (await extractImageThumb(image, 192)).buffer;
        if (upload) {
            const uploaded = await Promise.race([
                prepareWAMessageMedia({ image }, {
                    upload,
                    mediaTypeOverride: 'thumbnail-link',
                    mediaUploadTimeoutMs: 4000
                }),
                delay(6500, undefined, { ref: false })
            ]);
            if (uploaded?.imageMessage?.directPath) {
                preview.highQualityThumbnail = uploaded.imageMessage;
            }
        }
    } catch (error) {
        console.warn('YouTube thumbnail unavailable:', error.name);
    }
    return preview;
}

module.exports = { youtubePreview };
