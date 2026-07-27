import { create } from 'zustand'

import { readStoredJson, safeLocalStorage } from '../storage'

export const useAuthStore = create((set) => ({
  user: readStoredJson('user'),
  token: safeLocalStorage.getItem('token'),

  setAuth: (user, token) => {
    safeLocalStorage.setItem('token', token)
    safeLocalStorage.setItem('user', JSON.stringify(user))
    set({ user, token })
  },

  logout: () => {
    safeLocalStorage.removeItem('token')
    safeLocalStorage.removeItem('user')
    set({ user: null, token: null })
  },

  updateUser: (updates) =>
    set((state) => {
      const updated = { ...state.user, ...updates }
      safeLocalStorage.setItem('user', JSON.stringify(updated))
      return { user: updated }
    }),
}))

export const useNotificationStore = create((set) => ({
  unreadCount: 0,
  setUnreadCount: (count) => set({ unreadCount: count }),
  increment: () => set((state) => ({ unreadCount: state.unreadCount + 1 })),
  decrement: () =>
    set((state) => ({ unreadCount: Math.max(0, state.unreadCount - 1 })),
}))
