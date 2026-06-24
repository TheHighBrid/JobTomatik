import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { login } from '../api/client'
import { useAuthStore } from '../store'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  const mut = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: (res) => {
      setAuth(res.data.user, res.data.access_token)
      toast.success('Welcome back!')
      navigate('/')
    },
    onError: (err) => toast.error(err.response?.data?.detail || 'Login failed'),
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
              onKeyDown={(e) => e.key === 'Enter' && mut.mutate()}
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
              onKeyDown={(e) => e.key === 'Enter' && mut.mutate()}
            />
          </div>
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !email || !password}
            className="btn-primary w-full mt-2"
          >
            {mut.isPending ? 'Signing in…' : 'Sign in'}
          </button>
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
