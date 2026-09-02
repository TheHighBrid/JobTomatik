import CurrentLeverOperatorPanel from '../components/CurrentLeverOperatorPanel'
import CurrentLeverRuntimeControl from '../components/CurrentLeverRuntimeControl'
import CurrentLeverTargetForm from '../components/CurrentLeverTargetForm'

export default function CurrentLeverOperator() {
  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-gray-900">Current Lever Operator</h1>
          <p className="mt-1 text-sm text-gray-500">
            Owner-selected supervised Lever applications, without terminal commands.
          </p>
        </div>
        <CurrentLeverTargetForm />
      </div>
      <CurrentLeverRuntimeControl />
      <CurrentLeverOperatorPanel />
    </div>
  )
}
