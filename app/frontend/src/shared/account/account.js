/**
 * Community account service - signs in against the same Supabase project as
 * ssbmnucleus.net, so one account works on the website and in the app.
 * Mirrors meleeWebsite/frontend/src/services/auth.js (username-or-email login
 * via the api_login_email RPC; the users table is RLS-locked so anon email
 * lookups are not possible).
 */
import { createClient } from '@supabase/supabase-js'

// Public website credentials - the anon key ships in the ssbmnucleus.net
// bundle already; row-level security is what protects the data.
const SUPABASE_URL = 'https://nttxcjrnqccogsibeqzz.supabase.co'
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im50dHhjanJucWNjb2dzaWJlcXp6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAyMDY3NTYsImV4cCI6MjA3NTc4Mjc1Nn0.5EJaMlem2rASzuttx1_PtwGd2cuyAOtM8VJmwwiEudo'

export const REGISTER_URL = 'https://ssbmnucleus.net/register'
export const RESET_PASSWORD_URL = 'https://ssbmnucleus.net/forgot-password'

const WEBSITE_URL = 'https://ssbmnucleus.net'
const MEDIA_URL = 'https://media.ssbmnucleus.net'

// Mirrors the website's mediaUrl(): new avatars are absolute Supabase storage
// URLs; legacy ones are '/uploads/...' paths served from the R2 media host.
function resolveAvatarUrl(path) {
  if (!path) return null
  if (/^https?:\/\//.test(path)) return path
  if (path.startsWith('/uploads/')) return MEDIA_URL + path.slice('/uploads'.length)
  return WEBSITE_URL + path
}

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)

/** Current account ({id, username, email, is_admin} or null), from the stored session. */
export async function getAccount() {
  const { data: { session } } = await supabase.auth.getSession()
  if (!session?.user) return null
  return toAccount(session.user, await fetchProfile(session.user.id))
}

/** Sign in with username or email + password. Returns the account. */
export async function signIn(identifier, password) {
  let email = identifier.trim()
  if (!email.includes('@')) {
    const { data: foundEmail, error: lookupError } = await supabase
      .rpc('api_login_email', { p_username: email, p_password: password })
    if (lookupError || !foundEmail) throw new Error('Invalid username or password')
    email = foundEmail
  }
  const { data, error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) throw new Error(error.message)
  return toAccount(data.user, await fetchProfile(data.user.id))
}

/** Current Supabase access token, or null when signed out. Used by the
 * backend publish flow to call the website's intake RPCs as this user. */
export async function getAccessToken(expectedUserId) {
  const { data: { session } } = await supabase.auth.getSession()
  if (expectedUserId && session?.user?.id !== expectedUserId) return null
  return session?.access_token || null
}

export async function signOut() {
  const { error } = await supabase.auth.signOut()
  if (error) throw new Error(error.message)
}

/** Subscribe to session changes (sign-in/out, token refresh). Returns unsubscribe. */
export function onAccountChange(callback) {
  const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
    if (!session?.user) {
      callback(null)
      return
    }
    fetchProfile(session.user.id).then(profile => callback(toAccount(session.user, profile)))
  })
  return () => subscription.unsubscribe()
}

/** Call a Supabase edge function as the signed-in user (throws when signed
 * out or the function errors). Used for the Patreon/coach entitlement. */
export async function invokeEdgeFunction(name, body = {}) {
  const { data, error } = await supabase.functions.invoke(name, { body })
  if (error) throw new Error(error.message || `edge function ${name} failed`)
  return data
}

async function fetchProfile(userId) {
  const { data, error } = await supabase
    .from('users').select('*').eq('id', userId).single()
  return error ? null : data
}

function toAccount(user, profile) {
  return {
    id: user.id,
    username: profile?.username || user.user_metadata?.username || user.email?.split('@')[0] || 'user',
    email: user.email,
    is_admin: profile?.is_admin || false,
    avatarUrl: resolveAvatarUrl(profile?.avatar_url)
  }
}
