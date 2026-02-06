'use client'

import { useSession, signOut } from 'next-auth/react'
import { useRouter } from 'next/navigation'

export function AuthButton() {
  const { data: session, status } = useSession()
  const router = useRouter()

  if (status === 'loading') {
    return <div className="text-sm text-gray-500">Loading...</div>
  }

  if (session) {
    const displayName = session.user?.name || session.user?.email || "User"
    const handleSignOut = async () => {
      await signOut({ redirect: false })

      const domain = process.env.NEXT_PUBLIC_COGNITO_DOMAIN
      const clientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID
      const baseUrl = domain
        ? (domain.startsWith('http://') || domain.startsWith('https://') ? domain : `https://${domain}`)
        : ''

      if (baseUrl && clientId) {
        const logoutUri = encodeURIComponent(`${window.location.origin}/auth/signin`)
        window.location.href = `${baseUrl}/logout?client_id=${clientId}&logout_uri=${logoutUri}`
        return
      }

      router.replace('/auth/signin')
    }

    return (
      <div className="flex items-center gap-4">
        <span className="text-sm text-gray-700">
          Signed in as <strong>{displayName}</strong>
        </span>
        <button
          onClick={handleSignOut}
          className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-md hover:bg-red-700"
        >
          Sign Out
        </button>
      </div>
    )
  }

  return (
    <button
      onClick={() => router.push('/auth/signin')}
      className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
    >
      Sign In
    </button>
  )
}
