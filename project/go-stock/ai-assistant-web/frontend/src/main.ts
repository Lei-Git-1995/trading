import { createApp } from "vue";
import Root from "./Root.vue";
import "./style.css";
import "md-editor-v3/lib/preview.css";

const app = createApp(Root);
app.mount("#app");
