import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { getApiErrorMessage, isNetworkError, register } from '../api/client'
import ApiBaseUrlField from '../components/ApiBaseUrlField'
import { BrandMark } from '../components/BrandLogo'
import { useAuthStore } from '../store'

export default function Register() {
  const [form, setForm] = useState({ email: '', password: '', full_name: '' })
  const [error, setError] = useState('')
  const [showApiConnection, setShowApiConnection] = useState(false)
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  const mut = useMutation({
    mutationFn: () => register(form),
    onMutate: () => setError(''),
    onSuccess: (res) => {
      setAuth(res.data.user, res.data.access_token)
      toast.success('Account created! Welcome to JobTomatik.')
      navigate('/')
    },
    onError: (err) => {
      const message = getApiErrorMessage(err, 'Registration failed')
      setError(message)
      if (isNetworkError(err)) setShowApiConnection(true)
      toast.error(message)
    },
  })

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }))

  return (
    <div className="auth-canvas flex items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-7">
          <BrandMark className="mx-auto h-20 w-20 drop-shadow-2xl" />
          <div className="mt-4 text-3xl font-extrabold tracking-[-0.04em] text-white">
            Job<span className="brand-gradient-text">Tomatik</span>
          </div>
          <p className="mt-2 text-xs font-bold uppercase tracking-[0.18em] text-brand-gold">
            Smart automation. Better opportunities.
          </p>
          <h1 className="mt-7 text-2xl font-bold text-gray-900">Create your account</h1>
          <p className="text-gray-500 mt-1 text-sm">Build your profile once, then move through applications faster.</p>
        </div>

        <div className="auth-card rounded-2xl p-6 sm:p-7 space-y-5">
          <div>
            <label className="label" htmlFor="register-full-name">Full name</label>
            <input
              id="register-full-name"
              type="text"
              autoComplete="name"
              maxLength={200}
              className="input"
              placeholder="Jane Smith"
              value={form.full_name}
              onChange={set('full_name')}
            />
          </div>
          <div>
            <label className="label" htmlFor="register-email">Email</label>
            <input
              id="register-email"
              type="email"
              autoComplete="email"
              className="input"
              placeholder="you@example.com"
              value={form.email}
              onChange={set('email')}
            />
          </div>
          <div>
            <label className="label" htmlFor="register-password">Password</label>
            <input
              id="register-password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              className="input"
              placeholder="Minimum 8 characters"
              value={form.password}
              onChange={set('password')}
              onKeyDown={(e) => e.key === 'Enter' && !mut.isPending && mut.mutate()}
              aria-describedby="register-password-help"
            />
            <p id="register-password-help" className="mt-1.5 text-xs text-gray-500">
              Use at least 8 characters. Very long Unicode passwords may exceed bcrypt&apos;s 72-byte limit.
            </p>
          </div>
          <button
            type="button"
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !form.email || form.password.length < 8}
            className="btn-primary w-full mt-1"
          >
            {mut.isPending ? 'Creating account…' : 'Create account'}
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
          Already have an account?{' '}
          <Link to="/login" className="text-tomato-400 hover:text-tomato-300 hover:underline font-semibold">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
