import NextAuth from "next-auth"
import type { NextAuthConfig } from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"
import CognitoProvider from "next-auth/providers/cognito"

export const authConfig: NextAuthConfig = {
  providers: [
    // AWS Cognito - Primary authentication
    CognitoProvider({
      clientId: process.env.COGNITO_CLIENT_ID!,
      clientSecret: process.env.COGNITO_CLIENT_SECRET!,
      issuer: process.env.COGNITO_ISSUER, // e.g., https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xxxxxxxxx
    }),
    // Local credentials - Fallback for testing/emergency access
    CredentialsProvider({
      name: "Credentials",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" }
      },
      async authorize(credentials) {
        if (!credentials?.username || !credentials?.password) {
          return null
        }

        try {
          // Use API_URL for server-side calls (Docker internal network)
          // Falls back to NEXT_PUBLIC_API_URL for local development
          const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
          const loginUrl = `${apiUrl}/auth/login`
          
          console.log(`[Auth] Attempting login to: ${loginUrl}`)
          
          const response = await fetch(loginUrl, {
            method: 'POST',
            body: JSON.stringify({
              username: credentials.username,
              password: credentials.password
            }),
            headers: { "Content-Type": "application/json" }
          })

          if (!response.ok) {
            const errorText = await response.text()
            console.error(`[Auth] Login failed: ${response.status} - ${errorText}`)
            return null
          }

          const user = await response.json()
          console.log(`[Auth] Login successful for user: ${user.username}`)
          
          // Return user object with required fields
          if (user) {
            return {
              id: String(user.id || user.userId || "1"),
              name: user.name || user.username || credentials.username as string,
              email: user.email || `${credentials.username}@example.com`,
            }
          }

          return null
        } catch (error) {
          console.error('[Auth] Authentication error:', error)
          return null
        }
      }
    })
  ],
  pages: {
    signIn: '/auth/signin',
  },
  callbacks: {
    authorized({ auth, request: { nextUrl } }) {
      const isLoggedIn = !!auth?.user
      const isOnSignInPage = nextUrl.pathname === '/auth/signin'
      
      // Allow access to sign-in page without authentication
      if (isOnSignInPage) {
        // Redirect logged-in users away from sign-in page
        if (isLoggedIn) {
          return Response.redirect(new URL('/', nextUrl))
        }
        return true
      }
      
      // All other pages require authentication
      if (!isLoggedIn) {
        return false // Redirect to sign-in page
      }
      
      return true
    },
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id
      }
      return token
    },
    async session({ session, token }) {
      if (token && session.user) {
        session.user.id = token.id as string
      }
      return session
    },
  },
  secret: process.env.NEXTAUTH_SECRET,
}

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig)
