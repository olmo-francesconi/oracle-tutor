import { useEffect, useState } from 'react'
import { clearAdminToken, getAdminToken, setAdminUnauthorizedHandler } from '../lib/adminApi'
import { AdminLogin } from './AdminLogin'
import { AdminPage } from './AdminPage'

export function AdminApp() {
  const [isAuthed, setIsAuthed] = useState(() => Boolean(getAdminToken()))

  useEffect(() => {
    setAdminUnauthorizedHandler(() => setIsAuthed(false))
    return () => setAdminUnauthorizedHandler(null)
  }, [])

  if (!isAuthed) {
    return <AdminLogin onSuccess={() => setIsAuthed(true)} />
  }

  return (
    <AdminPage
      onLogout={() => {
        clearAdminToken()
        setIsAuthed(false)
      }}
    />
  )
}
