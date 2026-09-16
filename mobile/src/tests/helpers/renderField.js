// Render the real Field components in Node. Only native hosts and I/O boundaries are replaced.
// Dependencies: @babel/core, @babel/preset-react, @babel/plugin-transform-modules-commonjs,
// react and react-test-renderer (matching versions). CI installs these in a separate tooling directory.
const fs = require('fs');
const path = require('path');
const Module = require('module');
const babel = require('@babel/core');
const React = require('react');
const renderer = require('react-test-renderer');
global.IS_REACT_ACT_ENVIRONMENT = true;
const src = path.resolve(__dirname, '../..');
const boundaries = new Map();
const native = Object.fromEntries(['View', 'Text', 'TextInput', 'TouchableOpacity', 'ScrollView', 'Modal', 'ActivityIndicator'].map(n => [n, n]));
Object.assign(native, {
  StyleSheet: { create: v => v },
  Alert: { alert: () => {} },
  AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) },
  PanResponder: { create: handlers => ({ panHandlers: handlers }) },
});
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === 'react-native') return native;
  if (request === 'react-native-svg') return { __esModule: true, default: 'Svg', ...Object.fromEntries(['G', 'Polygon', 'Line', 'Circle', 'Rect', 'Text'].map(n => [n, n])) };
  if (request === '@react-navigation/native') return { useFocusEffect: cb => React.useEffect(cb, [cb]) };
  if (request.startsWith('.') && parent) {
    const resolved = path.resolve(path.dirname(parent.filename), request).replace(/\.js$/, '');
    if (boundaries.has(resolved)) return boundaries.get(resolved);
  }
  return originalLoad.call(this, request, parent, isMain);
};
const originalJs = Module._extensions['.js'];
Module._extensions['.js'] = function(mod, filename) {
  if (filename.startsWith(src + path.sep) && !filename.includes(path.sep + 'tests' + path.sep)) {
    const code = fs.readFileSync(filename, 'utf8');
    if (/\b(import|export)\s/.test(code)) {
      const result = babel.transformSync(code, { filename, babelrc: false, configFile: false,
        presets: [require.resolve('@babel/preset-react')], plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')] });
      return mod._compile(result.code, filename);
    }
  }
  return originalJs(mod, filename);
};
function boundary(name, value) { boundaries.set(path.join(src, name), value); }
async function render(Component, props) {
  let tree;
  await renderer.act(async () => { tree = renderer.create(React.createElement(Component, props)); });
  return tree;
}
async function press(tree, id) {
  const node = tree.root.findAll(n => n.type === 'TouchableOpacity' && n.props.testID === id)[0];
  if (!node) throw new Error('Missing button: ' + id);
  if (node.props.disabled) throw new Error('Button disabled: ' + id);
  await renderer.act(async () => { await node.props.onPress(); });
}
function textOf(tree) { return JSON.stringify(tree.toJSON()); }
async function unmount(tree) { if (tree) await renderer.act(async () => tree.unmount()); }
module.exports = { React, renderer, boundary, native, render, press, textOf, unmount };
