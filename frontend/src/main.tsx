import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./rose-theme.css";
import "./management.css";

document.documentElement.dataset.theme = "rose";

createRoot(document.getElementById("root")!).render(<App />);
