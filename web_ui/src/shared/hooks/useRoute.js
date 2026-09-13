import { useEffect, useState, useCallback } from 'react';
import { getRoute, navigate, subscribe } from '../../app/router';

// The React end of the router. Returns the current route and the same
// navigate every render, so it is safe in a dependency array.
export function useRoute() {
  const [route, setRoute] = useState(getRoute);

  useEffect(() => subscribe(setRoute), []);

  const go = useCallback((next, options) => navigate(next, options), []);

  return [route, go];
}

export default useRoute;
