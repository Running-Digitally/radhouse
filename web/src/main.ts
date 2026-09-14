import { mountWorkHome } from "./app.js";
const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("radhouse_app_root_missing");
mountWorkHome(root);
