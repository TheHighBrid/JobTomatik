import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { getApiBaseUrl, getApiErrorMessage, isNetworkError, login } from '../api/client'
import { getApiRoutingErrorMessage, isApiConfigurationError } from '../api/connection'
import ApiBaseUrlField from '../components/ApiBaseUrlField'
import { BrandMark } from '../components/BrandLogo'
import { useAuthStore } from '../store'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [showApiConnection, setShowApiConnection] = useState(false)
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  const mut = useMutation({
    mutationFn: () => login(email, password),
    onMutate: () => setError(''),
    onSuccess: (res) => {
      setAuth(res.data.user, res.data.access_token)
      toast.success('Welcome back!')
      navigate('/')
    },
    onError: (err) => {
      const apiBaseUrl = getApiBaseUrl()
      const message = (
        getApiRoutingErrorMessage(err, apiBaseUrl) ||
        getApiErrorMessage(err, 'Login failed')
      )
      setError(message)
      if (isNetworkError(err) || isApiConfigurationError(err, apiBaseUrl)) {
        setShowApiConnection(true)
      }
      toast.error(message)
    },
  })

  return (
    <div className="auth-canvas flex items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-7">
          <BrandMark className="mx-auto h-20 w-20 drop-shadow-2xl" />
          <div className="mt-4 text-3xl font-extrabold tracking-[-0.04em] text-white">
            Job<span className="brand-gradient-text">Tomatik</span>
          </div>
          <p className="mt-2 text-xs font-bold uppercase tracking-[0.18em] text-brand-gold">
            Automate. Apply. Achieve.
          </p>
          <h1 className="mt-7 text-2xl font-bold text-gray-900">Welcome back</h1>
          <p className="text-gray-500 mt-1 text-sm">Sign in to continue your job search command centre.</p>
        </div>

        <div className="auth-card rounded-2xl p-6 sm:p-7 space-y-5">
          <div>
            <label className="label" htmlFor="login-email">Email</label>
            <input
              id="login-email"
              type="email"
              autoComplete="email"
              className="input"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !mut.isPending && mut.mutate()}
            />
          </div>
          <div>
            <label className="label" htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              className="input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !mut.isPending && mut.mutate()}
            />
          </div>
          <button
            type="button"
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !email || !password}
            className="btn-primary w-full mt-1"
          >
            {mut.isPending ? 'Signing in…' : 'Sign in'}
          </button>
          {error && <p className="text-sm text-red-300 leading-relaxed" role="alert">{error}</p>}
        </div>

        <div className="mt-4 card p-4 text-sm space-y-3">
          <button
            type="button"
            onClick={() => setShowApiConnection((open) => !open)}
            className="w-full flex items-center justify-between text-left font-semibold text-gray-700"
            aria-expanded={showApiConnection}
          >
            <span>API connection</span>
            <span className="gold-accent text-lg leading-none">{showApiConnection ? '−' : '+'}</span>
          </button>
          {showApiConnection && <ApiBaseUrlField compact />}
        </div>

        <p className="text-center text-sm text-gray-500 mt-5">
          Don&apos;t have an account?{' '}
          <Link to="/register" className="text-tomato-400 hover:text-tomato-300 hover:underline font-semibold">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  )
}
