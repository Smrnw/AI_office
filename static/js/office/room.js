// Комната: стена с окнами (небо по времени суток) и деревянный пол.
import { W, H, WALL_Y, R, RO, mix, softShadow } from './core.js';

export const SKY = {
    night: { bands: ['#070b1f', '#0d1233', '#161a45', '#231f55', '#33296a', '#483575', '#5e4280'], far: '#120f2c', near: '#0b0920', beam: '147,197,253', beamA: 0.05, tint: 'rgba(14,22,64,0.24)', stars: true, lit: true },
    dawn: { bands: ['#1e1b4b', '#3d3377', '#6b4a8c', '#b0668f', '#e48a8a', '#f6b184', '#fbd7a0'], far: '#4a3560', near: '#2f2142', beam: '253,186,116', beamA: 0.07, tint: 'rgba(120,60,90,0.08)', stars: false, lit: true },
    day: { bands: ['#3aa6e8', '#58b9ee', '#7ccbf3', '#9bd8f6', '#b9e5f9', '#d3f0fb', '#e6f7fd'], far: '#8ea7bf', near: '#6f88a3', beam: '255,244,170', beamA: 0.10, tint: 'rgba(0,0,0,0)', stars: false, lit: false },
    dusk: { bands: ['#1e1b4b', '#43267a', '#7b2f86', '#c23f78', '#ee6a4b', '#f89a3a', '#fbc34a'], far: '#4a2858', near: '#2d1a3b', beam: '251,146,60', beamA: 0.08, tint: 'rgba(110,40,60,0.10)', stars: false, lit: true },
};

export function skyPhase() {
    const h = new Date().getHours();
    if (h >= 7 && h < 17) return 'day';
    if (h >= 17 && h < 20) return 'dusk';
    if (h >= 5 && h < 7) return 'dawn';
    return 'night';
}

// окна двумя группами; между ними и по краям - простенки для часов, картин и бра
export const WINDOWS = [250, 400, 550, 700, 950, 1100, 1250];
export const CLOCK = { x: 380, y: 41 };            // одни часы между первым и вторым окном

export function paintWall(sky, phase, lights, stars) {
    // обои: панели с тонкой полоской и лёгким рисунком
    R(-20, -20, W + 40, WALL_Y + 40, '#2f3449');
    for (let x = -20; x < W + 20; x += 32) {
        R(x, -20, 1, 132, 'rgba(255,255,255,0.035)');
        for (let y = 4; y < 108; y += 16) R(x + 15, y + ((x / 32) % 2) * 8, 2, 2, 'rgba(255,255,255,0.03)');
    }
    R(-20, -20, W + 40, 14, '#22263a'); R(-20, -8, W + 40, 2, '#3e4466');
    R(-20, 112, W + 40, WALL_Y - 112 + 20, '#262b3c');             // нижняя панель
    for (let x = -20; x < W + 20; x += 48) R(x, 116, 1, WALL_Y - 116, 'rgba(0,0,0,0.25)');
    R(-20, 110, W + 40, 3, '#474e74'); R(-20, 110, W + 40, 1, '#5c6595');

    WINDOWS.forEach((wx, i) => {
        softShadow(wx - 6, 120, 122, 8, 0.3);
        R(wx - 5, 16, 120, 104, '#11131d');
        R(wx - 3, 18, 116, 100, '#2c3149');
        for (let b = 0; b < 7; b++) R(wx + 4, 26 + b * 12, 102, 12, sky.bands[b]);
        if (phase === 'night' && i === 3) { R(wx + 70, 34, 14, 14, '#f4f1de'); R(wx + 74, 32, 12, 12, sky.bands[1]); }
        if (phase === 'day' && i === 1) { R(wx + 64, 32, 18, 18, '#fff3b0'); R(wx + 67, 35, 12, 12, '#ffe066'); }
        if ((phase === 'dusk' || phase === 'dawn') && i === 2) { R(wx + 34, 70, 18, 18, '#fbbf24'); R(wx + 38, 74, 10, 10, '#fde68a'); }
        if (phase === 'day') for (let c = 0; c < 2; c++) R(wx + 12 + mix(i * 7 + c) % 70, 36 + c * 10, 18, 4, 'rgba(255,255,255,0.75)');
        let bx = wx + 4, k = 0;
        while (bx < wx + 106) {                                    // дальний ряд домов
            const bh = 14 + mix(i * 31 + k * 7) % 28, bw = Math.min(10 + mix(i * 17 + k * 13) % 10, wx + 106 - bx);
            R(bx, 110 - bh, bw, bh, sky.far);
            if (mix(i + k) % 4 === 0) R(bx + bw / 2, 110 - bh - 6, 1, 6, sky.far);   // антенна
            bx += bw; k++;
        }
        bx = wx + 4; k = 0;
        while (bx < wx + 106) {                                    // ближний ряд с окошками
            const bh = 10 + mix(i * 53 + k * 11 + 5) % 28, bw = Math.min(12 + mix(i * 29 + k * 19) % 12, wx + 106 - bx);
            R(bx, 110 - bh, bw, bh, sky.near);
            R(bx, 110 - bh, bw, 1, 'rgba(255,255,255,0.08)');
            for (let n = 0; n < 8; n++) {
                const lx = bx + 2 + (n % 3) * 4, ly = 110 - bh + 3 + Math.floor(n / 3) * 6;
                if (lx + 3 < bx + bw && ly + 3 < 108 && mix(i * 97 + k * 5 + n) % 3 !== 0) {
                    lights.push({ x: lx, y: ly, c: mix(k + n + i) % 4 === 0 ? '#7dd3fc' : '#fde68a', s: mix(i * 3 + k + n * 11) % 240 });
                }
            }
            bx += bw; k++;
        }
        if (sky.stars) for (let s = 0; s < 7; s++) stars.push({ x: wx + 8 + mix(i * 7 + s) % 94, y: 29 + mix(i * 13 + s * 3) % 30, s: mix(i + s * 17) % 120 });
        for (let r = 0; r < 22; r++) R(wx + 64 - r * 1.8, 26 + r * 3.8, 8, 3.8, 'rgba(255,255,255,0.05)');
        R(wx + 53, 24, 4, 88, '#202337'); R(wx + 2, 66, 106, 4, '#202337');          // переплёт
        R(wx + 54, 24, 1, 88, '#3a3f5f'); R(wx + 2, 67, 106, 1, '#3a3f5f');
        RO(wx - 8, 116, 126, 7, '#3d4366', '#1a1d2c'); R(wx - 7, 117, 124, 1, '#646c9c');   // подоконник
    });

    // часы
    const { x: cx, y: cy } = CLOCK;
    R(cx - 14, cy - 14, 28, 28, '#151726');
    R(cx - 12, cy - 12, 24, 24, '#c9a24a');
    R(cx - 11, cy - 11, 22, 22, '#f2ede1');
    for (let a = 0; a < 12; a++) {
        const ang = a / 12 * Math.PI * 2;
        R(cx + Math.cos(ang) * 8.5 - 0.6, cy + Math.sin(ang) * 8.5 - 0.6, a % 3 ? 1 : 1.6, a % 3 ? 1 : 1.6, '#3b3b4f');
    }

    // картины и бра — только в простенках: окна занимают x от wx-5 до wx+115
    picture(836, 30, 50, 36, 0);
    picture(203, 44, 38, 30, 1);
    picture(900, 74, 30, 34, 2);
    picture(1400, 28, 74, 46, 0);
    picture(1500, 40, 34, 40, 1);
    [684, 1384, 1560].forEach(sx => {                                   // бра
        R(sx, 52, 8, 14, '#2b2b3d'); RO(sx - 2, 42, 12, 11, '#f2d98a', '#7a5a1c'); R(sx, 44, 8, 6, '#fff3c4');
    });
}

function picture(x, y, w, h, kind) {
    softShadow(x - 1, y + h, w + 2, 4, 0.35);
    RO(x, y, w, h, '#e7e1d3', '#1b1a26');
    R(x + 3, y + 3, w - 6, h - 6, ['#5aa9d6', '#c2587a', '#3f7d58'][kind]);
    if (kind === 0) {
        R(x + 3, y + h - 13, w - 6, 10, '#27496d'); R(x + 9, y + h - 19, 12, 8, '#3a6b97'); R(x + 20, y + h - 16, 14, 6, '#2f5b84');
        R(x + w - 14, y + 7, 6, 6, '#ffe066');
    } else if (kind === 1) {
        R(x + 5, y + h - 15, w - 10, 11, '#7a2742'); R(x + 9, y + 9, w - 18, 7, '#f6c1d0');
    } else {
        R(x + 6, y + h - 14, w - 12, 10, '#264d36'); R(x + 10, y + 8, 4, 14, '#7fbf8f'); R(x + 16, y + 12, 4, 10, '#a3d9b1');
    }
}

export function paintFloor(sky) {
    const PLANK = ['#8c4a2b', '#82432a', '#965230', '#7c3f27', '#8f4d2d'];
    for (let r = 0; r * 16 < H - WALL_Y + 16; r++) {
        const y = WALL_Y + r * 16;
        let x = -((r * 41) % 96), i = 0;
        while (x < W) {
            const n = mix(r * 13 + i * 7);
            R(x, y, 96, 16, PLANK[n % 5]);
            R(x + 8 + n % 40, y + 5, 30, 0.8, 'rgba(60,25,10,0.25)');           // волокна
            R(x + 20 + (n >> 5) % 40, y + 10, 24, 0.8, 'rgba(255,220,180,0.06)');
            R(x, y, 1, 16, 'rgba(0,0,0,0.25)');
            x += 96; i++;
        }
        R(-4, y + 15, W + 8, 1, 'rgba(0,0,0,0.22)');
        R(-4, y, W + 8, 1, 'rgba(255,255,255,0.05)');
    }
    softShadow(0, WALL_Y, W, 28, 0.45);
    R(0, WALL_Y - 6, W, 6, '#1d1f2c'); R(0, WALL_Y - 6, W, 1, '#4a4f72');      // плинтус
    WINDOWS.forEach(wx => {                                                     // свет из окон
        for (let r = 0; r < 46; r++) {
            const a = (sky.beamA * (1 - r / 50)).toFixed(3);
            R(wx + 6 + r * 1.7, WALL_Y + 2 + r * 4, 90, 4, 'rgba(' + sky.beam + ',' + a + ')');
        }
    });
}

export function drawClockHands(G, X, Y, SC) {
    const now = new Date();
    const mA = (now.getMinutes() + now.getSeconds() / 60) / 60 * Math.PI * 2 - Math.PI / 2;
    const hA = ((now.getHours() % 12) + now.getMinutes() / 60) / 12 * Math.PI * 2 - Math.PI / 2;
    const sA = now.getSeconds() / 60 * Math.PI * 2 - Math.PI / 2;
    const { x, y } = CLOCK;
    G.lineCap = 'round';
    G.strokeStyle = '#1f2937';
    G.lineWidth = Math.max(1, 1.4 * SC);
    G.beginPath();
    G.moveTo(X(x), Y(y)); G.lineTo(X(x + Math.cos(mA) * 8), Y(y + Math.sin(mA) * 8));
    G.moveTo(X(x), Y(y)); G.lineTo(X(x + Math.cos(hA) * 5), Y(y + Math.sin(hA) * 5));
    G.stroke();
    G.strokeStyle = '#dc2626';
    G.lineWidth = Math.max(1, 0.6 * SC);
    G.beginPath(); G.moveTo(X(x), Y(y)); G.lineTo(X(x + Math.cos(sA) * 9), Y(y + Math.sin(sA) * 9)); G.stroke();
}
