// Studio stylesheets, in cascade order. tokens.css holds custom properties only; every other file
// writes into the layers declared in vendor.css (vendor, base, kit, shell, surface, view, state).
import "./studio/tokens.css";
import "./studio/vendor.css";
import "./studio/base.css";
import "./studio/kit.css";
import "./studio/shell.css";
import "./studio/pages.css";
import "./studio/manage.css";
import "./studio/system.css";
import "./studio/canvas.css";
import "./studio/nodes.css";
import "./studio/composer.css";
import "./studio/composer-av.css";
import "./studio/results.css";
import "./studio/workspaces.css";
import "./studio/production.css";
import "./studio/dialogs.css";
import "./studio/engine.css";
import "./studio/setup.css";
import "./studio/prism.css";
import "./studio/safelight.css";
import { createRoot } from "react-dom/client";
import Root from "./Root";
import { applyAppearance } from "./design/appearance";

applyAppearance(); // before the first paint: no flash of the wrong palette
createRoot(document.getElementById("root")!).render(<Root />);