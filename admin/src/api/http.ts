import axios from 'axios'
import { installDemoAdapter } from '@/demo'

export const api = axios.create({ baseURL: '/' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('shenyu_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ?demo=1 时拦截读取请求返回演示数据（见 src/demo/）；不开关这行什么都不做
installDemoAdapter(api)
