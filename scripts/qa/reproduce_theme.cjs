// Run from apps/web: node <QA repo>/scripts/qa/reproduce_theme.cjs
const fs = require('fs');
const vm = require('vm');
const ts = require(require.resolve('typescript', { paths: [process.cwd()] }));
const data = {};
const attrs = {};
let listener;
const ctx = {
  exports: {},
  window: {
    localStorage: {
      getItem: k => data[k] ?? null,
      setItem: (k, v) => { data[k] = v; },
      removeItem: k => { delete data[k]; },
    },
    addEventListener: (event, fn) => { listener = fn; },
    removeEventListener: () => {},
  },
  document: { documentElement: {
    setAttribute: (k, v) => { attrs[k] = v; },
    removeAttribute: k => { delete attrs[k]; },
  } },
};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('lib/theme.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, ctx);
ctx.exports.applyTheme('light');
ctx.exports.subscribeTheme(() => {});
data['edge-theme'] = 'dark';
listener();
console.log('cross-tab', { stored: ctx.exports.readTheme(), rendered: attrs['data-theme'] });
ctx.window.localStorage.getItem = () => { throw Error('blocked'); };
ctx.window.localStorage.setItem = () => { throw Error('blocked'); };
ctx.exports.applyTheme('light');
console.log('blocked-storage', {
  state: ctx.exports.readTheme(), rendered: attrs['data-theme'],
  next: ctx.exports.nextTheme(ctx.exports.readTheme()),
});
