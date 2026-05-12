import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Planets from './pages/Planets'
import PlanetDetail from './pages/PlanetDetail'
import StarMap from './pages/StarMap'
import Alerts from './pages/Alerts'
import Rankings from './pages/Rankings'

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/planets" element={<Planets />} />
        <Route path="/planets/:name" element={<PlanetDetail />} />
        <Route path="/stars" element={<StarMap />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/rankings" element={<Rankings />} />
      </Route>
    </Routes>
  )
}

export default App

