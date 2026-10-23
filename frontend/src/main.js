import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import App from './App.vue'
import router from './router'
import { purgeLegacyToken } from './api/token'

// 令牌存储已由 localStorage 改为 sessionStorage（关闭浏览器即退出登录）。
// 这里清一次旧版可能残留的 localStorage 令牌，避免它继续被误认为是登录态。
purgeLegacyToken()

const app = createApp(App)
app.use(ElementPlus)
app.use(router)
app.mount('#app')
