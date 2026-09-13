import { useCallback, useSyncExternalStore } from 'react';
import { getRoute, navigate, subscribe } from '../../app/router';

// useSyncExternalStore closes the window between first render and the
// subscribe effect: a navigation fired by another component's mount effect
// used to reach no subscriber and leave this one on a stale route.
//
// It requires getRoute() to return the same object reference while the URL
// is unchanged — router.js caches it for exactly this reason.
export function useRoute() {
  const route = useSyncExternalStore(subscribe, getRoute, getRoute);
  const go = useCallback((next, options) => navigate(next, options), []);
  return [route, go];
}

export default useRoute;
