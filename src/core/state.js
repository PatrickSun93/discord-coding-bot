const userQueues = new Map();
const userCwds = new Map();
const userBackends = new Map();

function enqueueForUser(userId, task) {
  const prev = userQueues.get(userId) || Promise.resolve();
  const next = prev.then(task, task);
  userQueues.set(userId, next);
  next.finally(() => {
    if (userQueues.get(userId) === next) userQueues.delete(userId);
  });
  return next;
}

module.exports = {
  userCwds,
  userBackends,
  enqueueForUser,
};
