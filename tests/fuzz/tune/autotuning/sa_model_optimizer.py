# This is the Python adaptation and derivative work of TVM (https://github.com/apache/incubator-tvm/).
# Copyright 2019 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cost model optimizer based on simulated annealing"""

import heapq
import logging
import time
import numpy as np

logger = logging.getLogger('fuzz.tune.autotuning.sa_model_optimizer')

class SimulatedAnnealingOptimizer:
    """parallel simulated annealing optimization algorithm

    Parameters
    ----------
    space: ConfigSpace
        The search space of configs
    n_iter: int
        The number of iterations of simulated annealing
    temp: float or Array of float
        If is a single float, then use a constant temperature.
        If is an Array, then perform linear cooling from temp[0] to temp[1]
    early_stop: int, optional
        Stop iteration if the optimal set do not change in `early_stop` rounds
    log_interval: int, optional
        Print log every `log_interval` iterations
    """

    def __init__(self, space, n_iter=500, temp=(1, 0), persistent=True, parallel_size=128,
                 early_stop=50, log_interval=50):
        self.space = space
        self.n_iter = n_iter
        self.temp = temp
        self.persistent = persistent
        self.parallel_size = min(parallel_size, self.space.length)
        self.early_stop = early_stop or 1e9
        self.log_interval = log_interval
        self.points = None

    def find_best(self, model, num, exclusive):
        """find best configs based on simulated annealing"""
        tic = time.time()
        temp, n_iter, early_stop, log_interval = self.temp, self.n_iter, self.early_stop, self.log_interval

        if self.persistent and self.points is not None:
            points = self.points
        else:
            points = np.random.choice(self.space.length, self.parallel_size)

        scores = 1e8 / model.predict(points)

        # build heap and insert initial points
        heap_items = [(float('-inf'), -i) for i in range(num)]
        heapq.heapify(heap_items)
        in_heap = set(exclusive)
        in_heap.update([-i for i in range(num)])

        for s, p in zip(scores, points):
            if s > heap_items[0][0] and p not in in_heap:
                pop = heapq.heapreplace(heap_items, (s, p))
                in_heap.remove(pop[1])
                in_heap.add(p)

        k = 0
        k_last_modify = 0

        if isinstance(temp, (tuple, list, np.ndarray)):
            t = temp[0]
            cool = 1.0 * (temp[0] - temp[1]) / (n_iter + 1)
        else:
            t = temp
            cool = 0

        while k < n_iter and k < k_last_modify + early_stop:
            new_points = np.empty_like(points)
            for i, p in enumerate(points):
                new_points[i] = self.space.random_walk(p)

            new_scores = 1e8 / model.predict(new_points)

            ac_prob = np.exp(np.minimum((new_scores - scores) / (t + 1e-5), 1))
            ac_index = np.random.random(len(ac_prob)) < ac_prob

            points[ac_index] = new_points[ac_index]
            scores[ac_index] = new_scores[ac_index]

            for s, p in zip(new_scores, new_points):
                if s > heap_items[0][0] and p not in in_heap:
                    pop = heapq.heapreplace(heap_items, (s, p))
                    in_heap.remove(pop[1])
                    in_heap.add(p)
                    k_last_modify = k

            k += 1
            t -= cool

            if log_interval and k % log_interval == 0:
                t_str = "%.2f" % t
                logger.debug("SA iter: %d\tlast_update: %d\tmax-0: %.2f\tmax-1: %.2f\ttemp: %s\t"
                             "elapsed: %.2f",
                             k, k_last_modify, heap_items[0][0],
                             np.max([v for v, _ in heap_items]), t_str,
                             time.time() - tic)

        heap_items.sort(key=lambda item: -item[0])
        logger.debug("SA iter: %d\tlast_update: %d\tmax-0: %.2f\tmax-1: %.2f\telapsed: %.2f",
                     k, k_last_modify, heap_items[-1][0], heap_items[0][0], time.time() - tic)
        logger.debug("SA Maximums: %s", heap_items)

        if self.persistent:
            self.points = points

        return [x[1] for x in heap_items]
