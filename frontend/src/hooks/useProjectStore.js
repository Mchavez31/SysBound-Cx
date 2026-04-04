import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const useProjectStore = create(
  persist(
    (set) => ({
      activeProjectId: null,
      activeProject: null,
      setActiveProject: (project) => set({ activeProjectId: project?.id || null, activeProject: project }),
      clearActiveProject: () => set({ activeProjectId: null, activeProject: null }),
    }),
    {
      name: 'project-storage',
      partialize: (s) => ({ activeProjectId: s.activeProjectId, activeProject: s.activeProject }),
    }
  )
)

export default useProjectStore
