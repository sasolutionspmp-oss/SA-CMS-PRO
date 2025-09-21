const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("saCms", {
  version: "0.1.0",
});
