import { createApp } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElConfigProvider,
  ElDatePicker,
  ElDrawer,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElPagination,
  ElPopover,
  ElProgress,
  ElSegmented,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTabPane,
  ElTag,
  ElLoading,
} from 'element-plus'
import 'element-plus/dist/index.css'
import './styles.css'
import './console.css'
import App from './App.vue'
import router from './router'
import TableScroll from './components/TableScroll.vue'
const app = createApp(App).use(router)
app.component('TableScroll', TableScroll)
for (const component of [
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElConfigProvider,
  ElDatePicker,
  ElDrawer,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElPagination,
  ElPopover,
  ElProgress,
  ElSegmented,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTabPane,
  ElTag,
])
  app.use(component)
app.directive('loading', ElLoading.directive)
app.mount('#app')
