/*
 * majiang-ui 浏览器打包配置（webpack，纯 JS 无原生二进制）
 *
 * 输出 dist/majiang-ui.js：入口 src/index.js 将 @kobalab/majiang-core
 * 与 @kobalab/majiang-ui 组装为浏览器全局对象 window.Majiang。
 */
"use strict";

const path = require("path");

module.exports = {
    mode: "production",
    entry: "./src/index.js",
    output: {
        path: path.resolve(__dirname, "dist"),
        filename: "majiang-ui.js",
    },
    devtool: false,
    optimization: {
        minimize: true,
    },
};
