import { useState } from 'react'
import { clearAdminToken, getAdminToken } from '../lib/adminApi'
import { AdminLogin } from './AdminLogin'
import { AdminPage } from './AdminPage'

export function AdminApp() {
  const [isAuthed, setIsAuthed] = useState(() => Boolean(getAdminToken()))

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
