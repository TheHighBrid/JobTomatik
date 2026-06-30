import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { register } from '../api/client'
import ApiBaseUrlField from '../components/ApiBaseUrlField'
import { useAuthStore } from '../store'

export default function Register() {
  const [form, setForm] = useState({ email: '', password: '', full_name: '' })
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  const mut = useMutation({
    mutationFn: () => register(form),
    onSuccess: (res) => {
      setAuth(res.data.user, res.data.access_token)
      toast.success('Account created! Welcome to JobTomatik.')
      navigate('/')
    },
    onError: (err) => toast.error(err.response?.data?.detail || 'Registration failed'),
  })

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="min-h-screen bg-gradient-to-br from-tomato-50 to-white flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex w-14 h-14 bg-tomato-600 rounded-2xl items-center justify-center text-white font-bold text-2xl mb-4">
            JT
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Create account</h1>
          <p className="text-gray-500 mt-1 text-sm">Start automating your job search</p>
        </div>

        <div className="card p-6 space-y-4">
          <div>
            <label className="label">Full name</label>
            <input
              type="text"
              className="input"
              placeholder="Jane Smith"
              value={form.full_name}
              onChange={set('full_name')}
            />
          </div>
          <div>
            <label className="label">Email</label>
            <input
              type="email"
              className="input"
              placeholder="you@example.com"
              value={form.email}
              onChange={set('email')}
            />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              type="password"
              className="input"
              placeholder="Minimum 8 characters"
              value={form.password}
              onChange={set('password')}
              onKeyDown={(e) => e.key === 'Enter' && mut.mutate()}
            />
          </div>
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !form.email || !form.password}
            className="btn-primary w-full mt-2"
          >
            {mut.isPending ? 'Creating account…' : 'Create account'}
          </button>
        </div>

        <details className="mt-4 card p-4 text-sm">
          <summary className="cursor-pointer font-medium text-gray-700">API connection</summary>
          <div className="mt-3">
            <ApiBaseUrlField compact />
          </div>
        </details>

        <p className="text-center text-sm text-gray-500 mt-4">
          Already have an account?{' '}
          <Link to="/login" className="text-tomato-600 hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
