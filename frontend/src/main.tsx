import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./studio-theme.css";
import "./management.css";
import "./motion/motion.css";
import "./motion/motion.js";

createRoot(document.getElementById("root")!).render(<App />);
