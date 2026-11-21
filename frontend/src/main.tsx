import "./design/tokens.css"; // design tokens first: custom properties only
import { createRoot } from "react-dom/client";
import Root from "./Root";
import "./styles.css";
import "./studio-theme.css";
import "./management.css";
import "./motion/motion.css";
import "./design/button.css"; // shared Button / IconButton; before states.css so the shared disabled rule applies
import "./design/states.css"; // shared interaction states (disabled, status); after the theme files
import "./design/pale-pink.css"; // light palette layer; last so it can restyle literal-coloured surfaces
import { applyAppearance } from "./design/appearance";

applyAppearance(); // before the first paint: no dark flash for the light palette
createRoot(document.getElementById("root")!).render(<Root />);
