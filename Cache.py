
import sys, os, random
import numpy as np
import pandas as pd


class Cache(object):

    # Elasped terms - short, middle and long
    FEAT_TREMS = [10, 100]

    def __init__(self, progs, cache_size, allow_skip=True, delay_reward=False, interval=0, boot=False):
        # Basics
        self.allow_skip = allow_skip
        self.delay_reward = delay_reward    # Only for policy-based

        # Counters
        self.total_count = 0
        self.miss_count = 0
        self.evict_count = 0

        # Requests
        self.requests = []
        self.operations = []
        if isinstance(progs, str): progs = [progs]
        for prog in progs:
            df = pd.read_csv(prog, header=0)
            if not boot: df = df.loc[df['boot/exec'] == 1, :]
            self.requests += list(df['blocksector'])
            self.operations += list(df['read/write'])

        self.cur_index = -1

        if len(self.requests) <= cache_size:
            raise ValueError("The count of requests are too small. Try larger one.")

        if len(self.requests) != len(self.operations):
            raise ValueError("Not every request is assigned with an operation.")

        # Cache
        self.cache_size = cache_size
        self.slots = [-1] * self.cache_size
        self.used_times = [-1] * self.cache_size
        self.cached_times = [-1] * self.cache_size
        self.access_bits = [False] * self.cache_size
        self.dirty_bits = [False] * self.cache_size
        self.resource_freq = {}

        # Action & feature information
        self.n_actions = self.cache_size + 1 if allow_skip else self.cache_size
        self.n_features = (self.cache_size + 1) * len(Cache.FEAT_TREMS) + self.cache_size*0

    # Display the current cache state
    def display(self):
        print(self.slots)

    # Return miss rate
    def miss_rate(self):
#         print("%d / %d = %f" % (self.miss_count, self.total_count, self.miss_count / self.total_count))
        # print("%f" % (self.miss_count / self.total_count))
        return self.miss_count / self.total_count

    def reset(self):
        self.total_count = 0
        self.miss_count = 0

        self.cur_index = 0

        self.slots = [-1] * self.cache_size
        self.used_times = [-1] * self.cache_size
        self.access_bits = [False] * self.cache_size
        self.dirty_bits = [False] * self.cache_size

        slot_id = 0
        while slot_id < self.cache_size and self.cur_index < len(self.requests):
#             if self.cur_index % 100 == 99:
#                 self.miss_rate()

            request = self._current_request()
            if request not in self.slots:
                self.miss_count += 1
                self.slots[slot_id] = request
                self.cached_times[slot_id] = self.cur_index
                self._hit_cache(slot_id)
                slot_id += 1
            self.total_count += 1
            self.cur_index += 1

        # Back to the last requested index
        self.cur_index -= 1

        # Run to the first miss as the inital decision epoch.
        self._run_until_miss()

        return self._get_observation()

    # Has program finished?
    def hasDone(self):
        return self.cur_index == len(self.requests)

    # Make action at the current decision epoch and run to the
    # next decision epoch.
    def step(self, action):
        if self.hasDone():
            raise ValueError("Simulation has finished, use reset() to restart simulation.")

        if not self.allow_skip:
            action += 1

        if action < 0 or action > len(self.slots):
            raise ValueError("Invalid action %d taken." % action)

        # Evict slot of (aciton - 1). action == 0 means skipping eviction.
        if action != 0:
            out_resource = self.slots[action - 1]
            in_resource = self._current_request()
            slot_id = action - 1
            self.slots[slot_id] = in_resource
            self.cached_times[slot_id] = self.cur_index
            self._hit_cache(slot_id)
            self.evict_count += 1
        else:
            skip_resource = self._current_request()

        last_index = self.cur_index

        # Proceed kernel and resource accesses until next miss.
        self._run_until_miss()

        # Get observation.
        observation = self._get_observation()

        # Compute reward: R = hit reward + miss penalty
        reward = 0.0

        # Total count of hit since last decision epoch
        hit_count = self.cur_index - last_index - 1
        if hit_count != 0: reward += 1.0

        start = last_index
        end = last_index + 100
        if end > len(self.requests): end = len(self.requests)
        long_term_hit = 0
        next_reqs = self.requests[start : end]
        for rc in self.slots:
            long_term_hit += next_reqs.count(rc)
        reward += 0.5 * long_term_hit / (end - start)

#         hit_count = self.cur_index - last_index - 1
#         reward += hit_count

#         miss_resource = self._current_request()
#         # If evction happens at last decision epoch
#         if action != 0:
#             # Compute the swap-in reward
#             past_requests = self.requests[last_index + 1 : self.cur_index]
#             reward += 10 * past_requests.count(in_resource)
#             # Compute the swap-out penalty
#             if miss_resource == out_resource:
#                 reward -= 100 / (hit_count + 1) + 5
#         # Else no evction happens at last decision epoch 
#         else:
#             # Compute the reward of skipping eviction
#             reward += 0.3 * reward
#             # Compute the penalty of skipping eviction
#             if miss_resource == skip_resource:
#                 reward -= 100 / (hit_count + 1) + 5

        return observation, reward

    # Run until next cache miss
    def _run_until_miss(self):
        self.cur_index += 1
        while self.cur_index < len(self.requests):
            request = self._current_request()
            self.resource_freq[request] = self.resource_freq.get(request, 0) + 1
            self.total_count += 1
            if request not in self.slots:
                self.miss_count += 1
                break
            else:
                slot_id = self.slots.index(request)
                self._hit_cache(slot_id)
            self.cur_index += 1
        return self.hasDone()

    # In case that the simulation has ended, but we still need the current
    # request for the last observation and reward. Return -1 to eliminate
    # any defects.
    def _current_request(self):
        return -1 if self.hasDone() else self.requests[self.cur_index]

    # Simulate cache hit, update attributes.
    def _hit_cache(self, slot_id):
        # Set access bit
        self.access_bits[slot_id] = True
        # If the operation is write
        if self.operations[self.cur_index] == 1:
            # Set dirty bit
            self.dirty_bits[slot_id] = True
        # Record last used time
        self.used_times[slot_id] = self.cur_index

    # The number of requests on rc_id among last `term` requests.
    def _elapsed_requests(self, term, rc_id):
#         start = self.cur_index + 1
        start = self.cur_index - term + 1
        if start < 0: start = 0
        end = self.cur_index + 1
#         end = self.cur_index + term
        if end > len(self.requests): end = len(self.requests)
        return self.requests[start : end].count(rc_id)

    # The number of requests on rc_id among next `term` requests.
    def _next_requests(self, term, rc_id):
        start = self.cur_index + 1
        if start < 0: start = 0
        end = self.cur_index + term
        if end > len(self.requests): end = len(self.requests)
        return self.requests[start : end].count(rc_id)

    # Return the observation features for reinforcement agent
    def _get_features(self):
        # [Freq, F1, F2, ..., Fc] where Fi = [Rs, Rm, Rl]
        # i.e. the request times in short/middle/long term for each
        # cached resource and the currently requested resource.


        features = np.concatenate([
            np.array([self._elapsed_requests(t, self._current_request()) for t in Cache.FEAT_TREMS])
            , np.array([self._elapsed_requests(t, rc) for rc in self.slots for t in Cache.FEAT_TREMS])

            # Uncomment to enable different features.
            # , np.array([self.used_times[i] for i in range(self.cache_size)])
            # , np.array([self.cached_times[i] for i in range(self.cache_size)])
        ], axis=0)
        
        return features

    def _get_observation(self):
        return dict(features=self._get_features(),
            cache_state=self.slots.copy(),
            cached_times=self.cached_times.copy(),
            last_used_times=self.used_times.copy(),
            access_bits=self.access_bits.copy(),
            dirty_bits=self.dirty_bits.copy()
        )
