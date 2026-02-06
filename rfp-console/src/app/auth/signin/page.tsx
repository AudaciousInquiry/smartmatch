'use client'

import { signIn } from 'next-auth/react'
import { useState } from 'react'

export default function SignIn() {
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleCognitoSignIn = async () => {
    setError('')
    setLoading(true)
    try {
      await signIn('cognito', { callbackUrl: '/', prompt: 'login' })
    } catch (error) {
      setError('Unable to start Cognito sign-in. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full space-y-8 p-8 bg-white rounded-lg shadow">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            SmartMatch Admin
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            Sign in to access the admin console
          </p>
        </div>
        <div className="mt-8 space-y-6">
          {error && (
            <div className="rounded-md bg-red-50 p-4">
              <div className="text-sm text-red-800">{error}</div>
            </div>
          )}
          <div>
            <button
              type="button"
              onClick={handleCognitoSignIn}
              disabled={loading}
              className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
            >
              {loading ? 'Redirecting...' : 'Sign in with Cognito'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
