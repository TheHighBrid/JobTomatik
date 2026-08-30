import CurrentLeverOperatorPanel from '../components/CurrentLeverOperatorPanel'

export default function CurrentLeverOperator() {
  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-gray-900">Current Lever Operator</h1>
        <p className="mt-1 text-sm text-gray-500">
          Owner-selected supervised Lever applications, without terminal commands.
        </p>
      </div>
      <CurrentLeverOperatorPanel />
    </div>
  )
}
