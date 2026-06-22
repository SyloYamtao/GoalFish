import { createApp } from 'vue'
import App from '../../src/App.vue'
import router from './router.js'
import i18n from '../../src/i18n'
import { installStaticApiMock } from './staticApi.js'

window.__GOALFISH_STATIC_DEMO__ = true
installStaticApiMock()

const app = createApp(App)
app.use(router)
app.use(i18n)
app.mount('#app')
