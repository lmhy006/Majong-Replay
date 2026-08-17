/*
 * majiang-ui 浏览器打包入口（阶段一）
 *
 * 将 @kobalab/majiang-core 与 @kobalab/majiang-ui 组装为浏览器
 * 全局对象 window.Majiang（与官方 README 的用法一致）：
 *
 *     const Majiang = require('@kobalab/majiang-core');
 *     Majiang.UI    = require('@kobalab/majiang-ui');
 *
 * 页面中通过 <script src="/static/majiang-ui/dist/majiang-ui.js">
 * 引入后，即可使用 Majiang.UI.Paipu 等回放组件。
 */
"use strict";

const Majiang = require("@kobalab/majiang-core");
Majiang.UI = require("@kobalab/majiang-ui");

window.Majiang = Majiang;
