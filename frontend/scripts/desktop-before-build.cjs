// The Electron shell uses only Electron and Node builtins. Dependencies for
// Next, rendering and npm are staged as separate resources by desktop:prepare.
// Returning false tells electron-builder those dependencies are handled here,
// so it neither rebuilds nor traverses the unrelated frontend dependency tree.
module.exports = async () => false;
