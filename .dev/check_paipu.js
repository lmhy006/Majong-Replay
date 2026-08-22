#!/usr/bin/env node
/* 验证 paipu JSON 能被 @kobalab/majiang-core Board 完整回放（阶段四调试用）。
 *
 * 用法：
 *     node .dev/check_paipu.js <paipu.json>
 */
const fs = require('fs');
const path = require('path');

const MAJIANG_CORE = path.resolve(
    __dirname,
    '../static/majiang-ui/node_modules/@kobalab/majiang-core'
);
const Majiang = require(MAJIANG_CORE);

const paipu = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const board = new Majiang.Board(paipu);
const errors = [];

for (let i = 0; i < paipu.log.length; i++) {
    const log = paipu.log[i];
    let j = 0;
    try {
        for (const data of log) {
            if (data.qipai) {
                board.qipai(data.qipai);
            } else if (data.zimo) {
                board.zimo(data.zimo);
            } else if (data.dapai) {
                board.dapai(data.dapai);
            } else if (data.fulou) {
                board.fulou(data.fulou);
            } else if (data.gang) {
                board.gang(data.gang);
            } else if (data.gangzimo) {
                board.zimo(data.gangzimo);
            } else if (data.kaigang) {
                board.kaigang(data.kaigang);
            } else if (data.hule) {
                board.hule(data.hule);
            } else if (data.pingju) {
                board.pingju(data.pingju);
            }
            j++;
        }
    } catch (e) {
        errors.push(`局 ${i} 事件 ${j}: ${JSON.stringify(log[j])} -> ${e.message}\n${e.stack}`);
    }
}

if (errors.length) {
    console.log('ERRORS:');
    for (const e of errors) console.log('  ' + e);
    process.exit(1);
} else {
    console.log(`OK: ${paipu.log.length} 局全部回放无错误`);
}
