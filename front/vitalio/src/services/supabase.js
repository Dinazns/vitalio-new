/**
 * Supabase client configuration
 */
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  const missing = []
  if (!supabaseUrl) missing.push('VITE_SUPABASE_URL')
  if (!supabaseAnonKey) missing.push('VITE_SUPABASE_ANON_KEY')
  
  throw new Error(
    `Missing Supabase configuration. Please add the following to your .env file:\n` +
    missing.map(v => `  ${v}=your-value-here`).join('\n') +
    `\n\nAfter adding these, restart your Vite dev server.`
  )
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
