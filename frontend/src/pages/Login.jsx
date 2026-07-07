import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { getApiErrorMessage, login } from '../api/client'
import ApiBaseUrlField from '../components/ApiBaseUrlField'
import { useAuthStore } from '../store'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
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
      const message = getApiErrorMessage(err, 'Login failed')
      setError(message)
      toast.error(message)
    },
  })

  return (
    <div className="min-h-screen bg-gradient-to-br from-tomato-50 to-white flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex w-14 h-14 bg-tomato-600 rounded-2xl items-center justify-center text-white font-bold text-2xl mb-4">
            JT
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Welcome back</h1>
          <p className="text-gray-500 mt-1 text-sm">Sign in to JobTomatik</p>
        </div>

        <div className="card p-6 space-y-4">
          <div>
            <label className="label">Email</label>
            <input
              type="email"
              className="input"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !mut.isPending && mut.mutate()}
            />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              type="password"
              className="input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !mut.isPending && mut.mutate()}
            />
          </div>
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !email || !password}
            className="btn-primary w-full mt-2"
          >
            {mut.isPending ? 'Signing in…' : 'Sign in'}
          </button>
          {error && <p className="text-sm text-red-600 leading-relaxed">{error}</p>}
        </div>

        <div className="mt-4 card p-4 text-sm space-y-3">
          <div>
            <h2 className="font-semibold text-gray-800">API connection</h2>
            <p className="text-xs text-gray-500 mt-1">
              Set and test the backend URL before signing in on Android.
            </p>
          </div>
          <ApiBaseUrlField compact />
        </div>

        <p className="text-center text-sm text-gray-500 mt-4">
          Don&apos;t have an account?{' '}
          <Link to="/register" className="text-tomato-600 hover:underline font-medium">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  )
}
