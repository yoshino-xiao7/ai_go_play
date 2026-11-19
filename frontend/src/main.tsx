import { createRoot } from "react-dom/client";
import Root from "./Root";
import "./styles.css";
import "./studio-theme.css";
import "./management.css";
import "./motion/motion.css";

createRoot(document.getElementById("root")!).render(<Root />);
