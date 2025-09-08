import React, { createContext, useContext, useState } from 'react'

type Store = { state: any; setState: React.Dispatch<React.SetStateAction<any>> }

const StoreContext = createContext<Store | undefined>(undefined)

export const StoreProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<any>({})
  return <StoreContext.Provider value={{ state, setState }}>{children}</StoreContext.Provider>
}

export const useStore = () => {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error('Store not available')
  return ctx
}
