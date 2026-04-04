import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import api from '../lib/api'

const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      login: async (email, password) => {
        // OAuth2 password flow expects application/x-www-form-urlencoded (not multipart FormData)
        const body = new URLSearchParams()
        body.append('username', email)
        body.append('password', password)
        const res = await api.post('/auth/login', body)
        const { access_token, user } = res.data
        api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
        set({ user, token: access_token, isAuthenticated: true })
        return user
      },

      register: async (name, email, password) => {
        const res = await api.post('/auth/register', { name, email, password })
        const { access_token, user } = res.data
        api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
        set({ user, token: access_token, isAuthenticated: true })
        return user
      },

      logout: () => {
        delete api.defaults.headers.common['Authorization']
        set({ user: null, token: null, isAuthenticated: false })
      },

      initAuth: () => {
        const token = get().token
        if (token) {
          api.defaults.headers.common['Authorization'] = `Bearer ${token}`
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ user: state.user, token: state.token, isAuthenticated: state.isAuthenticated }),
    }
  )
)

export default useAuthStore
