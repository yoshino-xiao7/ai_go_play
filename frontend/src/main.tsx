import "./design/tokens.css"; // design tokens first: custom properties only
import { createRoot } from "react-dom/client";
import Root from "./Root";
import "./styles.css";
import "./studio-theme.css";
import "./management.css";
import "./motion/motion.css";
import "./design/button.css"; // shared Button / IconButton; before states.css so the shared disabled rule applies
import "./design/states.css"; // shared interaction states (disabled, status); after the theme files

createRoot(document.getElementById("root")!).render(<Root />);
