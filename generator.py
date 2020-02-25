"""
# -*- coding: latin_1 -*-
"""
import sqlite3
import random
import time
import json
import copy
import numpy
import math
import os
import argparse
from scipy.special import softmax
from scipy.stats import entropy
from collections import defaultdict

parser = argparse.ArgumentParser()
parser.add_argument('-d', '--db_id', type=int, default=1)
args = parser.parse_args()
db_ids_to_ignore = [124, 131]


def transform2distribution_proportional(scores):
	# strip the negative values to zero (the negative values were there in the first hand
	# because of considerations for softmax)
	temp_scores = []
	for item in scores:
		if item < 0:
			temp_scores.append(0)
		else:
			temp_scores.append(item)
	total = float(sum(temp_scores))
	dist = []
	for item in temp_scores:
		dist.append(item / total)
	return dist


def transform2distribution_softmax(scores):
	dist = softmax(scores)
	return dist


# a placeholder function
def chinese_split_words(c_chinese):
	return [c_chinese]


def cut_value_for_like(v, mode):
	v = v.strip('"')
	v = v.strip("'")

	len_dist = [0.01] + [1] * (len(v) - 1) + [0.01]
	len_dist[1] += len(v)
	if len(v) - 2 > 1:
		len_dist[2] += len(v)
	if len(v) - 2 > 2:
		len_dist[3] += len(v)
	if len(v) - 2 > 3:
		len_dist[4] += int(len(v) / 2)
	if len(v) - 2 > 4:
		len_dist[5] += int(len(v) / 3)
	len_dist = transform2distribution_proportional(len_dist)
	length = numpy.random.choice(range(len(v) + 1), p=len_dist)
	if length == 0:
		length = 1
	if mode == 'mid':
		start_point_dist = [1] * len(v)
		# favor middle characters to the left a little bit as starting point more
		for idx in range(len(v)):
			if idx == 0 or idx == len(v) - 1:
				start_point_dist[idx] = 0.1
			else:
				start_point_dist[idx] += (idx + 1) * (len(v) - idx)
		start_point_dist = transform2distribution_proportional(start_point_dist)
		start_point = numpy.random.choice(range(len(v)), p=start_point_dist)
		start_point = min(start_point, len(v) - 1)
		length = min(length, len(v) - start_point)
		if length == 0:
			length = 1
		slice = v[start_point:start_point + length]
		slice = '%' + slice + '%'
	elif mode == 'head':
		length = min(length, len(v))
		slice = v[:length]
		slice = slice + '%'
	elif mode == 'tail':
		length = min(length, len(v))
		slice = v[len(v) - length:]
		slice = '%' + slice
	else:
		raise AssertionError
	return slice


transform2distribution = transform2distribution_proportional

DATABASE_PATH = './spider/spider/database'
TABLE_MATADATA_PATH = './spider/spider/tables_mod.json'
SAVE_PATH = './saved_results/'

tableid = 0
propertyid = 0

ITR_TRY = 1000
NAME_PAIR_WEIGHT = 0.2
MAX_VALUE_ENTRIES = 500

# test for git commit

PAGERANK_CRITICAL_VALUE = 0.0000000001
PAGERANK_QVALUE = 0.2  # a baseline score with which probability the traverse jumps to a random node

CALCULABLE_DTYPES = ['int', 'double']
SUBTRACTABLE_DTYPES = CALCULABLE_DTYPES + ['datetime', 'year']
ORDERBY_DTYPES = ['int', 'datetime', 'year', 'double', 'id', 'timestamp']
UNLIKELY_COND_DTYPES = ['timestamp', 'blob',
						'bit']  # those dtypes that are unlikely present in where / having / join-on conditions
ALL_DTYPES = ['int', 'varchar(1000)', 'double', 'id', 'datetime', 'bit', 'bool', 'timestamp', 'year', 'blob']

# the probability of 'in' for CMP_DISTS is constantly zero,
# since those cases with 'in' are covered saperately in function #construct_ci_cdts#

# 1 -> between; 2 -> =; 3 -> >; 4 -> <; 5 -> >=; 6 -> <=; 7 -> !=; 8 -> in; 9 -> like
CMP_DISTS = {'int': transform2distribution_proportional([38, 309, 252, 99, 35, 18, 7, 80, 0]),
			 'double': transform2distribution_proportional([24, 16, 190, 65, 12, 4, 4, 2, 0]),
			 'varchar(1000)': transform2distribution_proportional([0, 2306, 27, 16, 3, 0, 106, 30, 164]),
			 'id': transform2distribution_proportional([2, 63, 2, 0, 0, 0, 4, 166, 0]),
			 'bit': transform2distribution_proportional([0, 2, 0, 0, 0, 0, 0, 0, 0]),
			 'datetime': transform2distribution_proportional([2, 8, 22, 21, 4, 4, 0, 0, 4]),
			 'bool': transform2distribution_proportional([0, 10, 0, 0, 0, 0, 0, 0, 0]),
			 'timestamp': transform2distribution_proportional([0, 1, 0, 0, 0, 0, 1, 1, 0]),
			 'year': transform2distribution_proportional([0, 1, 1, 1, 1, 1, 1, 1, 0]),
			 'blob': transform2distribution_proportional([0, 1, 0, 0, 0, 0, 1, 1, 0])}
# for those types without actual data in SPIDER, assign equal probability to each feasible comparer
# convert into default_dicts in order to be compatible with more database dtypes
CMP_DISTS = defaultdict(lambda: [0, 1, 0, 0, 0, 0, 1, 1, 0], CMP_DISTS)

AGGR_DISTS = {'int': transform2distribution_proportional([0, 1, 1, 5, 1, 2]),
			  'double': transform2distribution_proportional([0, 1, 1, 5, 1, 2]),
			  'varchar(1000)': transform2distribution_proportional([0, 0, 0, 1, 0, 0]),
			  'id': transform2distribution_proportional([0, 0, 0, 1, 0, 0]),
			  'bit': transform2distribution_proportional([0, 0, 0, 1, 0, 0]),
			  'datetime': transform2distribution_proportional([0, 1, 1, 5, 0, 0]),
			  'bool': transform2distribution_proportional([0, 0, 0, 1, 0, 0]),
			  'timestamp': transform2distribution_proportional([0, 0, 0, 1, 0, 0]),
			  'year': transform2distribution_proportional([0, 1, 1, 5, 0, 0]),
			  'blob': transform2distribution_proportional([0, 0, 0, 1, 0, 0])}

# convert into default_dicts in order to be compatible with more database dtypes
AGGR_DISTS = defaultdict(lambda: [0, 0, 0, 1, 0, 0], AGGR_DISTS)


def calc_num_queries_via_stats_regressed(num_rels):
	res = 76 + 3 * num_rels
	assert res > 0
	res = int(min(res, 300))
	return res


calc_num_queries_via_stats = calc_num_queries_via_stats_regressed


# built-in functions
# THE RESULTS OF DATA AGGREGATION SHOULD BE VALUENP?
# data aggregation
def _avg(x):
	assert (isinstance(x, PROPERTYNP))
	assert (x.dtype in CALCULABLE_DTYPES)
	# the property to be averaged must be single
	c_english = 'the average of {0} %s' % x.c_english
	c_chinese = '%s的平均值' % x.c_chinese
	z = 'AVG(%s)' % x.z
	return c_english, c_chinese, z, False


def _min(x):
	assert (isinstance(x, PROPERTYNP))
	assert (x.dtype in SUBTRACTABLE_DTYPES)
	c_english = 'the smallest %s' % x.c_english
	c_chinese = '%s的最小值' % x.c_chinese
	z = 'MIN(%s)' % x.z
	return c_english, c_chinese, z, False


def _max(x):
	assert (isinstance(x, PROPERTYNP))
	assert (x.dtype in SUBTRACTABLE_DTYPES)
	c_english = 'the largest %s' % x.c_english
	c_chinese = '%s的最大值' % x.c_chinese
	z = 'MAX(%s)' % x.z
	return c_english, c_chinese, z, False


def _sum(x):
	assert (isinstance(x, PROPERTYNP))
	assert (x.dtype in CALCULABLE_DTYPES)
	c_english = 'the sum of %s' % x.c_english
	c_chinese = '%s的总和' % x.c_chinese
	z = 'SUM(%s)' % x.z
	return c_english, c_chinese, z, False


def _uniquecount(x):
	assert (isinstance(x, PROPERTYNP))

	# the count must be of integer type, specifically ordinal integer type
	rho = random.random()
	if rho < 0.4 and x.dtype != 'star':
		distinct = True
		c_english = 'the number of different values of %s' % x.c_english
		c_chinese = '%s不同取值的数量' % x.c_chinese
		z = 'COUNT(distinct %s)' % x.z
	else:
		distinct = False
		c_english = 'the number of %s' % x.c_english
		c_chinese = '%s的数量' % x.c_chinese
		z = 'COUNT(%s)' % x.z
	return c_english, c_chinese, z, distinct


def _repeat(x):
	return x.c_english, x.c_chinese, x.z, False


def is_comparable(str1, str2):
	if str1 in CALCULABLE_DTYPES and str2 in CALCULABLE_DTYPES:
		return True
	elif 'varchar' in str1 and 'varchar' in str2 and str1 == str2:
		return True
	elif str1 == str2:
		return True
	else:
		return False


def pagerank_scores(matrix):
	matrix = numpy.matrix(matrix)
	assert (matrix.ndim == 2)
	assert (matrix.shape[0] == matrix.shape[1])
	last_scores = [1] * matrix.shape[0]
	weightsums = matrix.sum(axis=1, dtype='float').flatten()
	while True:
		scores = [PAGERANK_QVALUE] * matrix.shape[0]
		for i in range(matrix.shape[0]):
			for j in range(matrix.shape[1]):
				# divide score with total sum of weights of the source table
				scores[j] += ((1 - PAGERANK_QVALUE) * matrix[i, j] * last_scores[i]) / weightsums[0, i]
		if last_scores is None:
			continue
		assert (len(last_scores) == len(scores))
		# check whether the scores are stable at this round
		stable = True
		for a, b in zip(last_scores, scores):
			if abs(a - b) > PAGERANK_CRITICAL_VALUE:
				stable = False
				break
		if stable:
			break
		else:
			last_scores = scores
	return last_scores


# table_ids means the previous tables already selected into this query
def calc_importance(type_mat, table_ids, prior_scores=None):
	if len(table_ids) == 0:
		scores = pagerank_scores(type_mat)
	else:
		assert (prior_scores is not None)
		scores = [0] * type_mat.shape[0]
		in_and_out = type_mat + type_mat.T
		# for each existing table in query, add its influence matrix (in_and_out)
		# adjusted with its own prior importance to the scoring of next table
		for idx_1 in range(len(type_mat)):
			for idx_2 in table_ids:
				scores[idx_1] += in_and_out[idx_1, idx_2] * prior_scores[idx_2]
	return scores


def fetch_join_rel(new_tid, table_ids, prop_rels, typenps, propertynps, allow_pseudo_rels=False):
	relevant_prop_rels = []
	for idx, rel in enumerate(prop_rels):
		# allow only those relations whose types are both used in query
		if rel.table_ids[0] in table_ids and rel.table_ids[1] == new_tid:
			relevant_prop_rels.append(rel)
		elif rel.table_ids[0] == new_tid and rel.table_ids[1] in table_ids:
			relevant_prop_rels.append(rel)
	# if there are actual relations
	if len(relevant_prop_rels) > 0:
		scores = []
		for rel in relevant_prop_rels:
			scores.append(rel.score)
		scores = numpy.array(scores)
		dist = transform2distribution(scores)
		try:
			fetched_rel = numpy.random.choice(relevant_prop_rels, p=dist)
		except Exception as e:
			print(e)
			raise
	# if no actual relations exist
	elif allow_pseudo_rels:
		left_available_propids = typenps[new_tid].properties
		right_available_propids = []
		for tid in table_ids:
			right_available_propids += typenps[tid].properties
		pseudo_rels = []
		for pid1 in left_available_propids:
			for pid2 in right_available_propids:
				if propertynps[pid1].dtype == propertynps[pid2].dtype:
					pseudo_rels.append([pid1, pid2])
		fetched_rel = random.choice(pseudo_rels)
		fetched_rel = PROP_REL(fetched_rel[0], fetched_rel[1], propertynps[fetched_rel[0]].table_id,
							   propertynps[fetched_rel[1]].table_id, 1)
	else:
		raise AssertionError

	cmper = copy.deepcopy(CMPERS[1])  # always use equality comparer
	c_english = propertynps[fetched_rel.prop_ids[0]].c_english.format(
		typenps[fetched_rel.table_ids[0]].c_english + '\'s ') + cmper.c_english.format(
		propertynps[fetched_rel.prop_ids[1]].c_english.format(typenps[fetched_rel.table_ids[1]].c_english + '\'s '))
	c_chinese = propertynps[fetched_rel.prop_ids[0]].c_chinese.format(
		typenps[fetched_rel.table_ids[0]].c_chinese + '的') + cmper.c_chinese.format(
		propertynps[fetched_rel.prop_ids[1]].c_chinese.format(typenps[fetched_rel.table_ids[1]].c_chinese + '的'))
	z = propertynps[fetched_rel.prop_ids[0]].z + cmper.z.format(propertynps[fetched_rel.prop_ids[1]].z)
	left = copy.deepcopy(propertynps[fetched_rel.prop_ids[0]])
	right = copy.deepcopy(propertynps[fetched_rel.prop_ids[1]])
	fetched_cdt = CDT(c_english, c_chinese, z, left, right, cmper)

	return fetched_cdt


def choose_proppair_for_cdt(left_available_prop_ids, right_available_prop_ids, propertynps, prop_mat):
	left_candidate_ids = []
	for idx in left_available_prop_ids:
		if propertynps[idx].dtype not in UNLIKELY_COND_DTYPES:
			left_candidate_ids.append(idx)

	right_candidate_ids = []
	for idx in right_available_prop_ids:
		if propertynps[idx].dtype not in UNLIKELY_COND_DTYPES:
			right_candidate_ids.append(idx)

	cand_prop_mat = []
	for i in left_candidate_ids:
		for j in right_candidate_ids:
			if prop_mat[i, j] == 0 or i == j or (is_comparable(propertynps[i].dtype, propertynps[j].dtype) is False):
				cand_prop_mat.append(-1000000)
			else:
				cand_prop_mat.append(prop_mat[i, j])
	try:
		cand_prop_dist = transform2distribution(cand_prop_mat)
	except Exception as e:
		return None, None
	pair_id = numpy.random.choice(numpy.arange(len(cand_prop_mat)), p=cand_prop_dist)
	left_id = left_candidate_ids[int(pair_id / len(right_candidate_ids))]
	right_id = right_candidate_ids[pair_id % len(right_candidate_ids)]
	return left_id, right_id


# 'in' comparer in where conditions appear only in those occasions with c-i conditions
# 
# use_aggr_for_left_prop is equal to true iff it is a having condition
def construct_cv_where_cdt(available_prop_ids, propertynps, use_aggr_for_left_prop=False, assigned_prop=None, no_negative=False):
	if assigned_prop is None:
		# the left-value in where conditions cannot have aggregators
		scores = [0] * len(available_prop_ids)
		for idx, prop_id in enumerate(available_prop_ids):
			if propertynps[prop_id].dtype in UNLIKELY_COND_DTYPES:
				scores[idx] = -10000
			elif propertynps[prop_id].dtype == 'id':
				scores[idx] *= 0.5
		# explicitly use softmax to convert into a distribution
		scores = transform2distribution_softmax(numpy.array(scores))
		chosen_prop_id = numpy.random.choice(available_prop_ids, p=scores)
		chosen_prop = copy.deepcopy(propertynps[chosen_prop_id])
		if use_aggr_for_left_prop:
			# assign different distributions for aggregators according to the property dtypes
			aggr_id = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=AGGR_DISTS[chosen_prop.dtype])
			chosen_prop.set_aggr(aggr_id)
	else:
		chosen_prop = assigned_prop

	if chosen_prop.aggr == 3:
		assert (AGGREGATION_FUNCTIONS[3] == _uniquecount)
		available_values = []
	else:
		available_values = chosen_prop.values

	# for 'COUNT(...)' clauses, '<' and '>' comparison operators are allowed, just as for 'int'
	if chosen_prop.aggr == 3:
		cmper_distribution = numpy.array(CMP_DISTS['int'])
	else:
		cmper_distribution = numpy.array(CMP_DISTS[chosen_prop.dtype])
	assert (len(cmper_distribution) == 9)
	cmper_distribution[7] = 0
	cmper_distribution = transform2distribution_proportional(cmper_distribution)

	cmper = copy.deepcopy(numpy.random.choice(CMPERS, p=cmper_distribution))

	if cmper.index == 1:
		num_values = 2
	else:
		num_values = 1
	if cmper.index == 2 and chosen_prop.dtype in ['int', 'double']:
		chosen_prop.c_english = 'is equal to {0}'
		chosen_prop.c_chinese = '与{0}相等'
	if cmper.index in [8, 9]:
		rho = random.random()
		if rho < 0.1 and not no_negative:
			cmper.set_negative()
	if available_values is None:
		raise AssertionError

	# print("num_values: ", num_values)
	if chosen_prop.aggr != 3:
		value = copy.deepcopy(
			numpy.random.choice(available_values, num_values,
								replace=False))  # object 'value' is list of either length 1 or length 2
		if cmper.index == 9:
			assert len(value) == 1
			v = value[0].z
			rho = random.random()
			if rho < 0.8:
				v = cut_value_for_like(v, mode='mid')
				cmper.set_mode('mid')
			elif rho < 0.95:
				v = cut_value_for_like(v, mode='head')
				cmper.set_mode('head')
			else:
				v = cut_value_for_like(v, mode='tail')
				cmper.set_mode('tail')
			value = [VALUENP(v.strip('%'), v.strip('%'), v, value[0].dtype)]
	else:
		count_dist = [0, 100, 150, 40]
		count_dist += [0.1] * 97
		count_dist[5] += 5
		for idx in range(10, 101, 10):
			count_dist[idx] += 0.4
		count_dist = transform2distribution_proportional(count_dist)
		value = random.choices(range(101), k=num_values, weights=count_dist)
		for i in range(len(value)):
			value[i] = VALUENP(str(value[i]), str(value[i]), str(value[i]), 'int')

	if num_values == 1:
		if not isinstance(value[0], VALUENP):
			raise AssertionError
		value_ce = value[0].c_english
		value_cc = value[0].c_chinese
		value_z = '#' + value[0].z + '#'
	else:
		value_ce = []
		value_cc = []
		value_z = []
		if value is None:
			raise AssertionError
		value.sort()  # 'between' requires that the two values are in ascending order
		if value is None:
			raise AssertionError
		for item in value:
			value_ce.append(item.c_english)
			value_cc.append(item.c_chinese)
			value_z.append('#' + item.z + '#')

	c_english = chosen_prop.c_english.format('') + cmper.c_english.format(value_ce)
	c_chinese = chosen_prop.c_chinese.format('') + cmper.c_chinese.format(value_cc)
	z = chosen_prop.z + ' ' + cmper.z.format(value_z)
	cdt = CDT(c_english, c_chinese, z, chosen_prop, value, cmper)
	return cdt


def construct_cc_where_cdt(available_prop_ids, propertynps, prop_mat, use_aggr_for_left_prop=False):
	left_prop_id, right_prop_id = choose_proppair_for_cdt(available_prop_ids, available_prop_ids, propertynps, prop_mat)
	if left_prop_id is None and right_prop_id is None:
		return None
	left_prop = copy.deepcopy(propertynps[left_prop_id])
	right_prop = copy.deepcopy(propertynps[right_prop_id])
	# there must not be aggregators in where conditions
	assert (left_prop.aggr == 0)
	assert (right_prop.aggr == 0)

	if use_aggr_for_left_prop:
		# assign different distributions for aggregators according to the property dtypes
		aggr_id = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=AGGR_DISTS[left_prop.dtype])
		left_prop.set_aggr(aggr_id)
	# does not allow for 'between' comparer for column-column conditions or column-subquery conditions
	cmper_distribution = transform2distribution_proportional(numpy.array(CMP_DISTS[left_prop.dtype][1:]))
	cmper_distribution[6] = 0
	cmper_distribution[7] = 0  # like operator at index 9-1-1=7 can never appear in c-c or c-i conditions
	cmper_distribution = transform2distribution_proportional(cmper_distribution)
	cmper = copy.deepcopy(numpy.random.choice(CMPERS[1:], p=cmper_distribution))
	if cmper.index in [8, 9]:
		rho = random.random()
		if rho < 0.1:
			cmper.set_negative()

	c_english = left_prop.c_english.format('') + cmper.c_english.format(right_prop.c_english.format(''))
	c_chinese = left_prop.c_chinese.format('') + cmper.c_chinese.format(right_prop.c_chinese.format(''))
	cdt = CDT(c_english, c_chinese, None, left_prop, right_prop, cmper)
	return cdt


# sub-queries can be either around properties with foreign key relations or same names, but rarely anything else
def construct_ci_where_cdt(available_prop_ids, typenps, propertynps, type_mat, prop_mat, prop_rels,
						   use_aggr_for_left_prop=False, cursor=None, no_negative=False):
	# only allow those with actual values
	all_prop_ids = []
	for i in range(len(propertynps)):
		if propertynps[i].valid:
			all_prop_ids.append(i)
	assert len(all_prop_ids) > 0
	left_prop_id, right_prop_id = choose_proppair_for_cdt(available_prop_ids, all_prop_ids, propertynps, prop_mat)
	if left_prop_id is None and right_prop_id is None:
		return None
	left_prop = copy.deepcopy(propertynps[left_prop_id])

	# does not allow for 'between' comparer for column-column conditions or column-subquery conditions
	cmper_distribution = transform2distribution_proportional(numpy.array(CMP_DISTS[left_prop.dtype][1:]))
	cmper_distribution[7] = 0  # like operator at index 9-1-1=7 can never appear in c-c or c-i conditions
	cmper = None
	if left_prop.dtype in CALCULABLE_DTYPES:
		cmper = copy.deepcopy(numpy.random.choice(CMPERS[1:], p=cmper_distribution))
	else:
		for item in CMPERS:
			if item.index == 8:  # if the comparer is 'in'
				cmper = copy.deepcopy(item)
	assert (cmper is not None)
	if cmper.index in [8, 9]:
		rho = random.random()
		if rho < 0.1 and not no_negative:
			cmper.set_negative()
	# the aggregators can only be max, min or avg (means can't have aggregator for non-number dtypes)
	if cmper.index != 8:  # if comparer is not 'in'
		use_aggr = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=AGGR_SUBQDIST)
	else:
		use_aggr = 0

	prop4right_subq = copy.deepcopy(propertynps[right_prop_id])
	prop4right_subq.set_aggr(use_aggr)

	right_subq_np, right_subq_qrynp = scratch_build(typenps, propertynps, type_mat, prop_mat, prop_rels,
													is_recursive=True,
													specific_props=[prop4right_subq], cursor=cursor,
													require_singlereturn=(cmper.index != 8))

	if use_aggr_for_left_prop:
		# assign different distributions for aggregators according to the property dtypes
		aggr_id = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=AGGR_DISTS[left_prop.dtype])
		left_prop.set_aggr(aggr_id)

	c_english = left_prop.c_english.format('') + cmper.c_english.format(
		' ( ' + right_subq_qrynp.c_english + ' ) ')
	c_chinese = left_prop.c_chinese.format('') + cmper.c_chinese.format('（' + right_subq_qrynp.c_chinese + '）')
	z = left_prop.z + cmper.z.format(' ( ' + right_subq_qrynp.z + ' ) ')
	cdt = CDT(c_english, c_chinese, z, left_prop, right_subq_qrynp, cmper)
	return cdt


# use entropy as a criterion for group by
def calc_group_score(dtype, values):
	if values is None:
		return 0
	value_buckets = {}
	for val in values:
		if val not in value_buckets:
			value_buckets[val] = 1
		else:
			value_buckets[val] += 1
	value_dist = []
	for val in value_buckets:
		value_dist.append(float(value_buckets[val]) / len(values))

	score = entropy(value_dist)
	return score


def choose_groupby_prop(groupable_prop_ids, propertynps, num_groupbys):
	group_scores = []
	for prop_id in groupable_prop_ids:
		group_scores.append(propertynps[prop_id].group_score)
	group_dist = transform2distribution(group_scores)
	num_groupbys = min(num_groupbys, len(groupable_prop_ids))
	try:
		propids_for_group = numpy.random.choice(groupable_prop_ids, num_groupbys, replace=False, p=group_dist)
	except Exception as e:
		print(e)
		raise
	available_after_group_by_prop_ids = find_available_propids_after_groupby(propertynps, propids_for_group)
	return propids_for_group, available_after_group_by_prop_ids


def find_available_propids_after_groupby(propertynps, propids_for_group):
	available_after_group_by_prop_ids = []
	for prop_id in propids_for_group:
		available_after_group_by_prop_ids.append(prop_id)
		# for the unique properties (such as id / name), all other unique properties
		# would also be available to go with no aggregators
		if propertynps[prop_id].is_unique:
			for idx, prop_j in enumerate(propertynps):
				if prop_j.table_id == propertynps[prop_id].table_id and prop_j.is_unique:
					available_after_group_by_prop_ids.append(idx)
	return available_after_group_by_prop_ids


def calc_forquery_distribution(available_prop_ids, groupby_prop_ids, propertynps):
	assert available_prop_ids is not None
	assert len(available_prop_ids) > 0
	# average probability of appearance as being queried is set according to stats from SPIDER
	scores = [0] * len(propertynps)
	for idx in available_prop_ids:
		if propertynps[idx].dtype == 'id':
			scores[idx] = 0.15
		elif propertynps[idx].dtype in ['datetime', 'int']:
			scores[idx] = 0.5
		elif 'varchar' in propertynps[idx].dtype:
			scores[idx] = 1.7
		else:
			scores[idx] = 1
	if groupby_prop_ids is not None:
		for idx in groupby_prop_ids:
			scores[idx] += 5
	scores = transform2distribution_proportional(scores)
	return scores


#	values	->	VALUENP
def is_unique(values):
	for idx_1, val_1 in enumerate(values):
		for idx_2, val_2 in enumerate(values):
			if idx_1 == idx_2:
				continue
			is_same = True
			if isinstance(val_1, list) or isinstance(val_1, tuple):
				assert isinstance(val_1, list) or isinstance(val_1, tuple)
				assert len(val_1) == len(val_2)
				for idx in range(len(val_1)):
					if val_1[idx] != val_2[idx]:
						is_same = False
						break
			else:
				if val_1 != val_2:
					is_same = False
			if is_same:
				return False
	return True


def all_the_same(lst):
	bucket = []
	for item in lst:
		assert isinstance(item, list) or isinstance(item, tuple)
		appeared = False
		for j in bucket:
			assert len(item) == len(j)
			is_same = True
			for idx in range(len(item)):
				if item[idx] != j[idx]:
					is_same = False
					break
			if is_same:
				appeared = True
				break

		if not appeared:
			bucket.append(item)
	if len(bucket) <= 1:
		return True
	elif len(bucket) > 1:
		return False


def either_contain(res_1, res_2):
	bucket_both = []
	bucket_1 = []
	bucket_2 = []
	for val_1 in res_1:
		assert isinstance(val_1, list) or isinstance(val_1, tuple)
		appeared = False
		for val_2 in bucket_1:
			is_same = True
			for idx in range(len(val_1)):
				if val_1[idx] != val_2[idx]:
					is_same = False
					break
			if is_same:
				appeared = True
				break
		if not appeared:
			bucket_1.append(val_1)

	for val_1 in res_2:
		assert isinstance(val_1, list) or isinstance(val_1, tuple)
		appeared = False
		for val_2 in bucket_2:
			is_same = True
			for idx in range(len(val_1)):
				if val_1[idx] != val_2[idx]:
					is_same = False
					break
			if is_same:
				appeared = True
				break
		if not appeared:
			bucket_2.append(val_1)

	for val_1 in res_1:
		assert isinstance(val_1, list) or isinstance(val_1, tuple)
		appeared = False
		for val_2 in bucket_both:
			is_same = True
			for idx in range(len(val_1)):
				if val_1[idx] != val_2[idx]:
					is_same = False
					break
			if is_same:
				appeared = True
				break
		if not appeared:
			bucket_both.append(val_1)

	for val_1 in res_2:
		assert isinstance(val_1, list) or isinstance(val_1, tuple)
		appeared = False
		for val_2 in bucket_both:
			is_same = True
			for idx in range(len(val_1)):
				if val_1[idx] != val_2[idx]:
					is_same = False
					break
			if is_same:
				appeared = True
				break
		if not appeared:
			bucket_both.append(val_1)
	if len(bucket_1) == len(bucket_both) or len(bucket_2) == len(bucket_both):
		return True
	else:
		return False


# set aggregator number 0 as returning the same as what's fed in
AGGREGATION_FUNCTIONS = [_repeat, _max, _min, _uniquecount, _sum, _avg]


class PROP_REL():
	def __init__(self, prop_source, prop_target, type_source, type_target, score):
		self.prop_ids = [prop_source, prop_target]
		self.table_ids = [type_source, type_target]
		self.score = score

	def print(self):
		print("----")
		print("prop_ids: ", self.prop_ids)
		print("table_ids: ", self.table_ids)
		print("score: ", self.score)
		print("~~~~")


class BASENP():
	# dtypes:
	#	self:			----
	#	c_english:		string
	#	c_chinese:		string
	#	z:				string
	def __init__(self, c_english, c_chinese, z):
		self.c_english = c_english
		self.c_chinese = c_chinese
		self.z = z


# TYPENP & NP has attributes; VALUENP, PROPERTYNP & CDT requires properties
# dtypes here down below are associated with 'attributes' like things, not 'property_names' like things

class TYPENP(BASENP):
	# dtypes:
	#	self:			----
	#	c_english:		string
	#	c_chinese:		string
	#	z:				string
	#	overall_idx:	int
	#	properties:		list		# contains the indices of its properties
	#	valid:			bool		# whether there are data entries in this table
	def __init__(self, c_english, c_chinese, z, overall_idx=None, properties=None):
		BASENP.__init__(self, c_english, c_chinese, z)
		if properties is None:
			properties = []
		self.overall_idx = overall_idx
		self.properties = properties
		self.valid = True
		self.clones = []

	def print(self):
		print("c_english: ", self.c_english)
		print("c_chinese: ", self.c_chinese)
		print("z: ", self.z)
		print("overall_idx: ", self.overall_idx)
		print("properties: ", self.properties)


class VALUENP(BASENP):
	# dtype here should strip off the '<type= >' thing
	# dtypes does not have same length as property_names,
	# it represents the dtypes of the resulting outputs of
	# the value required, not its ingradients.
	#
	# dtypes:
	#	self:			----
	#	c_english:		string
	#	c_chinese:		string
	#	z:				string
	#	dtype:			string
	def __init__(self, c_english, c_chinese, z, dtype):
		BASENP.__init__(self, c_english, c_chinese, z)
		self.dtype = dtype
		if 'varchar(1000)' in self.dtype or 'datetime' in self.dtype:
			assert isinstance(self.z, str)
			if self.z[0] != '"':
				self.z = '"' + self.z
			if self.z[-1] != '"':
				self.z = self.z + '"'
			if self.c_english[0] != '"':
				self.c_english = '"' + self.c_english
			if self.c_english[-1] != '"':
				self.c_english = self.c_english + '"'
			if self.c_chinese[0] != '"':
				self.c_chinese = '"' + self.c_chinese
			if self.c_chinese[-1] != '"':
				self.c_chinese = self.c_chinese + '"'

	def __lt__(self, other):
		if self.z < other.z:
			return True
		else:
			return False


# only take into consideration single property, the conbination of properties are dealt with at last step
# having an aggregator does not imply that it's single-valued, because there are group by clauses in it
class PROPERTYNP(BASENP):
	# dtypes:
	#	self:			----
	#	c_english:		string
	#	c_chinese:		string
	#	z:				string
	#	dtype:			string
	#	table_id:		int
	#	overall_index:	int
	#	meta_idx:		int			# The difference between meta_idx and overall_idx is that, meta_idx are the same
	#								# for clones but overall_idx are different
	#	values:			list		# The elements within are of VALUENP types since the z can be different form ce and cc
	#	aggr:			int
	#	from_sum:		bool
	#	from_cnt:		bool
	#	is_unique:		bool		# Whether each value in this property is unique
	#	valid:			bool		# Whether there are actual values in this column
	#	clones:			list		# Contains the overall_idx of the properties which are clones of this property from
	#								# same-table fk relations
	def __init__(self, c_english, c_chinese, z, dtype, table_id=None, overall_idx=None, values=None,
				 aggr=0, from_sum=False, from_cnt=False, is_unique=False, meta_idx=None):
		BASENP.__init__(self, c_english, c_chinese, z)
		self.dtype = dtype
		self.table_id = table_id
		self.overall_idx = overall_idx
		self.meta_idx = meta_idx
		self.values = values
		if self.values is not None:
			self.group_score = calc_group_score(self.dtype, self.values)
		self.aggr = aggr
		self.from_sum = from_sum
		self.from_cnt = from_cnt
		self.is_unique = is_unique
		self.valid = True
		self.clones = []
		self.distinct = False  # for aggregator 'COUNT', means whether it is 'count' or 'distinct count'

	def set_values(self, values):
		assert (values is not None)
		self.values = values
		self.group_score = calc_group_score(self.dtype, self.values)

	def set_aggr(self, aggr):
		if self.aggr != 0:
			print(self.aggr)
			raise AssertionError
		self.aggr = aggr
		self.c_english, self.c_chinese, self.z, self.distinct = AGGREGATION_FUNCTIONS[self.aggr](self)
		if self.aggr == 3:
			self.from_cnt = True
			self.values = numpy.arange(len(self.values)).tolist()
		elif self.aggr == 4:
			self.from_sum = True


# this setting aggregator is downstream relative to 'is_unique', therefore is irrelevant


class CMP(BASENP):
	# dtypes:
	#	self:			----
	#	c_english:		string
	#	c_chinese:		string
	#	z:				string
	def __init__(self, c_english, c_chinese, z, index):
		BASENP.__init__(self, c_english, c_chinese, z)
		self.index = index
		self.negative = False

	# when the comparer is either 'in' or 'like', with a probability randomly set the condition to be negative
	def set_negative(self):
		assert (self.negative is False)
		self.negative = True
		self.c_english = ' not ' + self.c_english
		self.c_chinese = '不' + self.c_chinese
		self.z = ' not ' + self.z

	def set_mode(self, mode):
		if mode == 'mid':
			self.c_english = ' contains ' + self.c_english
			self.c_chinese = '包含%s的' % self.c_chinese
		elif mode == 'head':
			self.c_english = ' starts with ' + self.c_english
			self.c_chinese = '以%s为开始的' % self.c_chinese
		elif mode == 'tail':
			self.c_english = ' ends with ' + self.c_english
			self.c_chinese = '以%s为结尾的' % self.c_chinese
		else:
			# 'mode' must be among 'mid', 'head' and 'tail'
			raise AssertionError


class CDT(BASENP):
	# dtypes:
	#	self:			----
	#	c_english:		string
	#	c_chinese:		string
	#	z:				string
	#	left:			PROPERTYNP
	#	right:			PROPERTYNP / VALUENP / QRYNP
	#	cmper:			CMP
	def __init__(self, c_english, c_chinese, z, left, right, cmper):
		BASENP.__init__(self, c_english, c_chinese, z)
		assert (isinstance(left, PROPERTYNP))
		assert (isinstance(cmper, CMP))
		self.left = left
		self.right = right
		self.cmper = cmper

	def fetch_z(self, temp_tabname_bucket):
		if isinstance(self.right, PROPERTYNP):
			res = self.left.z.format(temp_tabname_bucket[self.left.table_id]) + self.cmper.z.format(
				self.right.z.format(temp_tabname_bucket[self.right.table_id]))
		else:
			# in cv conditions, there might be cases where left column is star, then there need be no formatting
			if self.left.dtype == 'star':
				res = self.z
			else:
				res = self.z.format(temp_tabname_bucket[self.left.table_id])
		return res


class NP:
	# inherits all properties from prev_np if specified, then replace them with any assigned properties
	# dtypes:
	#	self:			----
	#	prev_np:		NP
	#	queried_props:	PROPERTYNP
	#	table_ids:		int
	#	join_cdts:		CDT
	#	cdts:			CDT
	#	cdt_linkers:	string
	#	group_props:	PROPERTYNP
	#	having_cdt:	CDT
	#	orderby_props:	PROPERTYNP
	#	orderby_order:	string
	#	limit:			int
	#	np_2:			NP
	#	qrynp_2:			QRYNP
	#	has_union:		bool
	#	distinct:		bool
	def __init__(self, prev_np=None, queried_props=None, table_ids=None, join_cdts=None,
				 cdts=[], cdt_linkers=[], group_props=None, having_cdt=None,
				 orderby_props=None, orderby_order=None, limit=None, np_2=None, qrynp_2=None, has_union=None,
				 has_except=None, has_intersect=None, distinct=False):
		if prev_np is not None:
			self.queried_props = copy.deepcopy(prev_np.queried_props)
			self.table_ids = copy.deepcopy(prev_np.table_ids)
			self.join_cdts = copy.deepcopy(join_cdts)
			self.cdts = copy.deepcopy(prev_np.cdts)
			self.cdt_linkers = copy.deepcopy(cdt_linkers)
			self.group_props = copy.deepcopy(prev_np.group_props)
			self.having_cdt = copy.deepcopy(prev_np.having_cdt)
			self.orderby_props = copy.deepcopy(prev_np.orderby_props)
			self.orderby_order = copy.deepcopy(prev_np.orderby_order)
			self.limit = copy.deepcopy(prev_np.limit)
			self.np_2 = copy.deepcopy(prev_np.np_2)
			self.qrynp_2 = copy.deepcopy(prev_np.qrynp_2)
			self.has_union = prev_np.has_union
			self.has_except = prev_np.has_except
			self.has_intersect = prev_np.has_intersect
			self.distinct = prev_np.distinct
		else:
			self.queried_props = None
			self.table_ids = None
			self.join_cdts = None
			self.cdts = None
			self.cdt_linkers = None
			self.group_props = None
			self.having_cdt = None
			self.orderby_props = None
			self.orderby_order = None
			self.limit = None
			self.np_2 = None
			self.qrynp_2 = None
			self.has_union = None
			self.has_except = None
			self.has_intersect = None
			self.distinct = distinct
		if queried_props is not None:
			for prop in queried_props:
				assert (isinstance(prop, PROPERTYNP))
			self.queried_props = copy.deepcopy(queried_props)
		if table_ids is not None:
			assert (join_cdts is not None)
			assert (len(join_cdts) <= len(table_ids))
			self.table_ids = copy.deepcopy(table_ids)
			self.join_cdts = copy.deepcopy(join_cdts)
		if cdts is not None:
			for cdt in cdts:
				assert (isinstance(cdt, CDT))
			self.cdts = copy.deepcopy(cdts)
			self.cdt_linkers = copy.deepcopy(cdt_linkers)
		if len(cdt_linkers) > 0:
			assert (cdts is not None)
			assert (len(cdt_linkers) + 1 == len(cdts))
		if group_props is not None:
			self.group_props = copy.deepcopy(group_props)
		if having_cdt is not None:
			self.having_cdt = copy.deepcopy(having_cdt)
		if orderby_props is not None:
			self.orderby_props = copy.deepcopy(orderby_props)
			assert (orderby_order is not None)
			self.orderby_order = copy.deepcopy(orderby_order)
		if limit is not None:
			self.limit = limit
		if np_2 is not None:
			self.np_2 = copy.deepcopy(np_2)
		if qrynp_2 is not None:
			self.qrynp_2 = copy.deepcopy(qrynp_2)
		flag = False
		if has_union is not None and has_union == True:
			flag = True
			self.has_union = has_union
		if has_except is not None and has_except == True:
			assert (flag is False)
			flag = True
			self.has_except = has_except
		if has_intersect is not None and has_intersect == True:
			assert (flag is False)
			flag = True
			self.has_intersect = has_intersect


class QRYNP:
	def __init__(self, np, typenps, propertynps, finalize_sequence=False):
		self.np = np
		self.z, self.z_toks, self.z_toks_novalue = self.process_z(typenps, propertynps)
		self.c_english_verbose = self.process_ce_verbose(typenps, propertynps)
		self.c_chinese_verbose = self.process_cc_verbose(typenps, propertynps)
		self.c_english_sequence = self.process_ce_step_by_step(typenps, propertynps, finalize=finalize_sequence)
		self.c_chinese_sequence = self.process_cc_step_by_step(typenps, propertynps, finalize=finalize_sequence)
		self.c_english = self.c_english_verbose
		self.c_chinese = self.c_chinese_verbose

	def process_z(self, typenps, propertynps):
		z = 'select '
		z_toks = ['select']

		if self.np.distinct:
			z += 'distinct '
			z_toks.append('distinct')

		# queried_props
		for idx, prop in enumerate(self.np.queried_props):
			if prop.dtype == 'star':
				z += prop.z.format('')
				z_toks.append(prop.z.format(''))
			elif len(self.np.table_ids) > 1:
				table_pos = None
				for i, item in enumerate(self.np.table_ids):
					if item == prop.table_id:
						table_pos = i
				z += prop.z.format('T{0}.'.format(table_pos))
				z_toks.append(prop.z.format('T{0}.'.format(table_pos)))
			else:
				z += prop.z.format(typenps[prop.table_id].z + '.')
				z_toks.append(prop.z.format(typenps[prop.table_id].z + '.'))

			if idx < len(self.np.queried_props) - 1:
				z += ' , '
				z_toks.append(',')

		if len(self.np.queried_props) == 0:
			z += '*'
			z_toks.append('*')

		# table_ids
		z += ' from '
		z_toks.append('from')
		table_names = []
		temp_tabname_bucket = {}
		for no, tabid in enumerate(self.np.table_ids):
			if len(self.np.table_ids) == 1:
				table_names.append(typenps[tabid].z)
				temp_tabname_bucket[tabid] = typenps[tabid].z + '.'
			else:
				table_names.append(typenps[tabid].z + ' as T%d ' % no)
				temp_tabname_bucket[tabid] = 'T%d.' % no

		z += (' ' + ' join '.join(table_names) + ' ')
		z_toks += (' ' + ' join '.join(table_names) + ' ').split(' ')

		# join_cdts
		if self.np.join_cdts is not None:
			if len(self.np.join_cdts) > 0:
				z += ' on '
				z_toks.append('on')
				join_cdt_zs = []
				for cond in self.np.join_cdts:
					join_cdt_zs.append(cond.fetch_z(temp_tabname_bucket))
				z += (' ' + ' and '.join(join_cdt_zs) + ' ')
				z_toks += (' ' + ' and '.join(join_cdt_zs) + ' ').split(' ')

		# where conditions
		if self.np.cdts is not None:
			if len(self.np.cdts) > 0:
				z += ' where '
				z_toks.append('where')
				for idx, cond in enumerate(self.np.cdts):
					if idx > 0:
						z += self.np.cdt_linkers[idx - 1]
						z_toks.append(self.np.cdt_linkers[idx - 1])
					z += (' ' + cond.fetch_z(temp_tabname_bucket) + ' ')
					z_toks += cond.fetch_z(temp_tabname_bucket).split(' ')

		# group bys
		if self.np.group_props is not None:
			if len(self.np.group_props) > 0:
				z += ' group by '
				z_toks += ['group', 'by']
				groupby_propnames = []
				for idx, prop in enumerate(self.np.group_props):
					groupby_propnames.append(prop.z.format(temp_tabname_bucket[prop.table_id]))
				z += (' ' + ', '.join(groupby_propnames) + ' ')
				z_toks += (' ' + ', '.join(groupby_propnames) + ' ').split()

		# having conditions
		if self.np.having_cdt is not None:
			z += ' having '
			z += self.np.having_cdt.fetch_z(temp_tabname_bucket)
			z_toks.append('having')
			z_toks += self.np.having_cdt.fetch_z(temp_tabname_bucket).split(' ')

		if self.np.orderby_props is not None:
			if len(self.np.orderby_props) > 0:
				z += ' order by '
				z_toks += ['order', 'by']
				orderby_propnames = []
				for idx, prop in enumerate(self.np.orderby_props):
					if prop.dtype == 'star':
						orderby_propnames.append(prop.z)
					else:
						orderby_propnames.append(prop.z.format(temp_tabname_bucket[prop.table_id]))
				z += (' ' + ', '.join(orderby_propnames) + ' ')
				z_toks += (' ' + ', '.join(orderby_propnames) + ' ').split()
			z += ' %s ' % self.np.orderby_order
			z_toks.append(self.np.orderby_order)

		if self.np.limit is not None:
			assert (self.np.limit > 0)
			z += 'limit %d' % self.np.limit
			z_toks += ['limit', '#%d#' % self.np.limit]  # use '#' to wrap the limit number as a 'value'

		if self.np.np_2 is not None:
			assert self.np.qrynp_2 is not None
			if self.np.has_union:
				z += ' union ' + self.np.qrynp_2.z
				z_toks.append('union')
				z_toks += self.np.qrynp_2.z_toks
			elif self.np.has_except:
				z += ' except ' + self.np.qrynp_2.z
				z_toks.append('except')
				z_toks += self.np.qrynp_2.z_toks
			elif self.np.has_intersect:
				z += ' intersect ' + self.np.qrynp_2.z
				z_toks.append('intersect')
				z_toks += self.np.qrynp_2.z_toks

		# use '#' as an indicator for values
		z_toks_novalue = []
		z_toks_stripped = []
		for item in z_toks:
			if isinstance(item, list):
				raise AssertionError
			if '#' not in item:
				z_toks_novalue.append(item)
				z_toks_stripped.append(item)
			else:
				z_toks_novalue.append('value')
				if not (item[0] == '#' or item[-1] == '#'):
					print(z)
					raise AssertionError
				z_toks_stripped.append(item.strip('#'))
		z = ' '.join(z_toks_stripped)

		z_toks_fin = []
		z_toks_novalue_fin = []
		for item in z_toks_stripped:
			if len(item) > 0:
				z_toks_fin.append(item)
		for item in z_toks_novalue:
			if len(item) > 0:
				z_toks_novalue_fin.append(item)

		return z, z_toks_fin, z_toks_novalue_fin

	def process_ce_verbose(self, typenps, propertynps):
		c_english = ''
		if self.np.group_props is not None:
			if len(self.np.group_props) > 0:
				c_english += ' for each value of '
		else:
			self.np.group_props = []
		for idx, prop in enumerate(self.np.group_props):
			c_english += prop.c_english.format('')
			if idx + 2 < len(self.np.group_props):
				c_english += ', '
			elif idx + 2 == len(self.np.group_props):
				c_english += ' and '

		if self.np.having_cdt is not None:
			c_english += ' having '
			c_english += self.np.having_cdt.c_english
		if self.np.group_props is not None:
			if len(self.np.group_props) > 0:
				c_english += ', '

		if self.np.distinct:
			c_english += 'all different values of '

		# queried_props
		tableid_of_last_prop = None
		for idx, prop in enumerate(self.np.queried_props):
			if isinstance(prop.table_id, list):
				c_english += prop.c_english
			else:
				if prop.table_id == tableid_of_last_prop:
					name = prop.c_english.format('')
				else:
					name = prop.c_english.format(typenps[prop.table_id].c_english + '\'s ')
					tableid_of_last_prop = prop.table_id
				c_english += name
			if idx + 2 < len(self.np.queried_props):
				c_english += ', '
			elif idx + 2 == len(self.np.queried_props):
				c_english += ' and '

		c_english += ' from '
		for idx, table_id in enumerate(self.np.table_ids):
			c_english += typenps[table_id].c_english
			if idx + 2 < len(self.np.table_ids):
				c_english += ', '
			elif idx + 2 == len(self.np.table_ids):
				c_english += ' and '

		if self.np.join_cdts is not None:
			if len(self.np.join_cdts) > 0:
				c_english += ' whose '
		else:
			self.np.join_cdts = []
		# all sorts of conditions
		for idx, cond in enumerate(self.np.join_cdts):
			c_english += cond.c_english
			if idx + 2 < len(self.np.join_cdts):
				c_english += ', '
			elif idx + 2 == len(self.np.join_cdts):
				c_english += ' and '

		if self.np.cdts is not None:
			if len(self.np.cdts) > 0:
				c_english += ', whose '
		else:
			self.np.cdts = []
		for idx, cond in enumerate(self.np.cdts):
			c_english += cond.c_english
			if idx + 1 < len(self.np.cdts):
				c_english += ' ' + self.np.cdt_linkers[idx] + ' '

		if self.np.limit is not None:
			limit_ce = 'top %d of ' % self.np.limit
		else:
			limit_ce = ''

		if self.np.orderby_props is not None:
			if len(self.np.orderby_props) > 0:
				assert self.np.orderby_order is not None
				if self.np.orderby_order == 'asc':
					_order = 'ascending'
				elif self.np.orderby_order == 'desc':
					_order = 'descending'
				else:
					raise AssertionError
				c_english += ', present %sthem in %s order of ' % (limit_ce, _order)
		else:
			self.np.orderby_props = []
		for idx, item in enumerate(self.np.orderby_props):
			c_english += item.c_english.format('')
			if idx + 1 < len(self.np.orderby_props):
				c_english += ', '

		if self.np.has_union:
			c_english = '( ' + c_english + ' ) combined with ( ' + self.np.qrynp_2.c_english + ' )'
		elif self.np.has_except:
			c_english = '( ' + c_english + ' ) except ( ' + self.np.qrynp_2.c_english + ' )'
		elif self.np.has_intersect:
			c_english = 'those in both ( ' + c_english + ' ) and ( ' + self.np.qrynp_2.c_english + ' )'

		return c_english

	def process_ce_step_by_step(self, typenps, propertynps, finalize=False):
		c_english = []
		sent_1 = 'Result {0[0]}: Find '
		if self.np.distinct:
			sent_1 += 'all different values of '

		# queried_props info
		tableid_of_last_prop = None
		# if there are no group-by clauses in this query, write down the ultimate version of queried props directly
		if self.np.group_props is None or len(self.np.group_props) == 0:
			for idx, prop in enumerate(self.np.queried_props):
				# if it is a '*' column
				if isinstance(prop.table_id, list):
					sent_1 += prop.c_english
				else:
					if prop.table_id == tableid_of_last_prop:
						name = prop.c_english.format('')
					else:
						name = prop.c_english.format(typenps[prop.table_id].c_english + '\'s ')
						tableid_of_last_prop = prop.table_id
					sent_1 += name
				if idx + 2 < len(self.np.queried_props):
					sent_1 += ', '
				elif idx + 2 == len(self.np.queried_props):
					sent_1 += ' and '
		else:
			# if there are group-by clauses in this query, at first we don't add use aggregators, instead we keep all entries
			for idx, prop in enumerate(self.np.queried_props):
				# if it is a '*' column
				if isinstance(prop.table_id, list):
					sent_1 += STAR_PROP.c_english
				else:
					if prop.table_id == tableid_of_last_prop:
						name = propertynps[prop.overall_idx].c_english.format('')
					else:
						name = propertynps[prop.overall_idx].c_english.format(typenps[prop.table_id].c_english + '\'s ')
						tableid_of_last_prop = prop.table_id
					sent_1 += name
				if idx + 2 < len(self.np.queried_props):
					sent_1 += ', '
				elif idx + 2 == len(self.np.queried_props):
					sent_1 += ' and '

		# table info
		sent_1 += ' from '
		for idx, table_id in enumerate(self.np.table_ids):
			sent_1 += typenps[table_id].c_english
			if idx + 2 < len(self.np.table_ids):
				sent_1 += ', '
			elif idx + 2 == len(self.np.table_ids):
				sent_1 += ' and '

		# join-on conditions info
		if self.np.join_cdts is not None:
			if len(self.np.join_cdts) > 0:
				sent_1 += ' whose '
		else:
			self.np.join_cdts = []
		for idx, cond in enumerate(self.np.join_cdts):
			sent_1 += cond.c_english
			if idx + 2 < len(self.np.join_cdts):
				sent_1 += ', '
			elif idx + 2 == len(self.np.join_cdts):
				sent_1 += ' and '
		c_english.append(sent_1)

		# where conditions info
		is_and = None  # whether the condition linker for where conditions is 'and'
		if self.np.cdts is None:
			self.np.cdts = []
		for idx, cond in enumerate(self.np.cdts):
			# allows for 'and' & 'or' linkers both present in a set of 'where' conditions (though not useful as of
			# SPIDER's scope)
			if is_and is None:
				cur_sent = 'Result {0[%d]}: From Result {0[%d]}, find those satisfying ' % (
					len(c_english), len(c_english) - 1)
			else:
				if is_and:
					cur_sent = 'Result {0[%d]}: From Result {0[%d]}, find those satisfying ' % (
						len(c_english), len(c_english) - 1)
				else:
					cur_sent = 'Result {0[%d]}: Find in addition to Result {0[%d]}, those from Result {0[%d]} satisfying ' % (
						len(c_english), len(c_english) - 1, 0)
			cur_sent += cond.c_english
			if idx < len(self.np.cdts) - 1:
				is_and = (self.np.cdt_linkers[idx] == 'and')  # is_and value may change from True to False
			c_english.append(cur_sent)

		# groupby info
		if self.np.group_props is not None:
			if len(self.np.group_props) > 0:
				groupby_sent = 'Result {0[%d]}: From Result {0[%d]}, for each value of ' % (
					len(c_english), len(c_english) - 1)
				for idx, prop in enumerate(self.np.group_props):
					groupby_sent += prop.c_english.format('')
					if idx + 2 < len(self.np.group_props):
						groupby_sent += ', '
					elif idx + 2 == len(self.np.group_props):
						groupby_sent += ' and '
				if self.np.having_cdt is not None:
					groupby_sent += ' where '
					groupby_sent += self.np.having_cdt.c_english

				# if there are group-by clauses in query, specify the aggregators of queried props along with the
				# group-by clause itself
				groupby_sent += ', find '
				if self.np.distinct:
					groupby_sent += 'all different values of '
				tableid_of_last_prop = None
				for idx, prop in enumerate(self.np.queried_props):
					# if it is a '*' column
					if isinstance(prop.table_id, list):
						groupby_sent += prop.c_english
					else:
						if prop.table_id == tableid_of_last_prop:
							name = prop.c_english.format('')
						else:
							name = prop.c_english.format(typenps[prop.table_id].c_english + '\'s ')
							tableid_of_last_prop = prop.table_id
						groupby_sent += name
					if idx + 2 < len(self.np.queried_props):
						groupby_sent += ', '
					elif idx + 2 == len(self.np.queried_props):
						groupby_sent += ' and '
				c_english.append(groupby_sent)

		if self.np.orderby_props is not None:
			if len(self.np.orderby_props) > 0:
				assert self.np.orderby_order is not None
				if self.np.limit is not None:
					limit_ce = 'top %d of ' % self.np.limit
				else:
					limit_ce = ''
				if self.np.orderby_order == 'asc':
					_order = 'ascending'
				elif self.np.orderby_order == 'desc':
					_order = 'descending'
				else:
					raise AssertionError
				orderby_sent = 'Result {0[%d]}: present %sResult {0[%d]} in %s order of ' % (
					len(c_english), limit_ce, len(c_english) - 1, _order)
				for idx, item in enumerate(self.np.orderby_props):
					orderby_sent += item.c_english.format('')
					if idx + 1 < len(self.np.orderby_props):
						orderby_sent += ' then '
				c_english.append(orderby_sent)

		if self.np.has_union or self.np.has_except or self.np.has_intersect:
			second_sents = self.np.qrynp_2.c_english_sequence
			len_cur_sents = len(c_english)
			len_second_sents = len(second_sents)
			second_sents = ' ### '.join(second_sents)
			second_sents = second_sents.format([('{0[%d]}' % (i + len(c_english))) for i in range(len_second_sents)])
			second_sents = second_sents.split(' ### ')
			c_english += second_sents
			if self.np.has_union:
				post_clause = 'Result {0[%d]}: return those in Result {0[%d]} as well as those in Result {0[%d]}' \
							  % (len(c_english), len_cur_sents - 1, len_cur_sents + len_second_sents - 1)
			elif self.np.has_except:
				post_clause = 'Result {0[%d]}: return those in Result {0[%d]} except those in Result {0[%d]}' \
							  % (len(c_english), len_cur_sents - 1, len_cur_sents + len_second_sents - 1)
			elif self.np.has_intersect:
				post_clause = 'Result {0[%d]}: return those in both Result {0[%d]} and Result {0[%d]}' \
							  % (len(c_english), len_cur_sents - 1, len_cur_sents + len_second_sents - 1)
			else:
				raise AssertionError
			c_english.append(post_clause)

		# in case of the upper most layer of recursion, finalize the sequence by replacing the '{0[xxx]}' number
		# placeholders with actual numbers 'xxx'
		if finalize:
			total_len = len(c_english)
			c_english = ' ### '.join(c_english)
			c_english = c_english.format([i for i in range(total_len)])
			c_english = c_english.split(' ### ')

		return c_english

	def process_cc_verbose(self, typenps, propertynps):
		c_chinese = ''
		if self.np.group_props is not None:
			if len(self.np.group_props) > 0:
				c_chinese += '对于每一个'
		else:
			self.np.group_props = []

		if self.np.having_cdt is not None:
			c_chinese += '满足'
			c_chinese += self.np.having_cdt.c_chinese
			c_chinese += '的'

		for idx, prop in enumerate(self.np.group_props):
			c_chinese += prop.c_chinese.format('')
			if idx + 2 < len(self.np.group_props):
				c_chinese += '、'
			elif idx + 2 == len(self.np.group_props):
				c_chinese += '和'
		if len(self.np.group_props) > 0:
			c_chinese += '，'

		c_chinese += '从'
		for idx, table_id in enumerate(self.np.table_ids):
			c_chinese += typenps[table_id].c_chinese
			if idx + 2 < len(self.np.table_ids):
				c_chinese += '、'
			elif idx + 2 == len(self.np.table_ids):
				c_chinese += '和'
		c_chinese += '中找出，'

		if self.np.join_cdts is not None:
			if len(self.np.join_cdts) > 0:
				c_chinese += '满足'
		else:
			self.np.join_cdts = []
		# all sorts of conditions
		for idx, cond in enumerate(self.np.join_cdts):
			c_chinese += cond.c_chinese
			if idx + 2 <= len(self.np.join_cdts):
				c_chinese += '、'
		if len(self.np.join_cdts) > 0:
			c_chinese += '的，'

		if self.np.cdts is not None:
			if len(self.np.cdts) > 0:
				c_chinese += '满足'
		else:
			self.np.cdts = []
		for idx, cond in enumerate(self.np.cdts):
			c_chinese += cond.c_chinese
			if idx + 1 < len(self.np.cdts):
				if self.np.cdt_linkers[idx] == 'or':
					c_chinese += '或'
				elif self.np.cdt_linkers[idx] == 'and':
					c_chinese += '且'
				else:
					raise AssertionError
		if len(self.np.cdts) > 0:
			c_chinese += '的，'

		# queried_props
		tableid_of_last_prop = None
		for idx, prop in enumerate(self.np.queried_props):
			if isinstance(prop.table_id, list):
				c_chinese += prop.c_chinese
			else:
				if prop.table_id == tableid_of_last_prop:
					name = prop.c_chinese.format('')
				else:
					name = prop.c_chinese.format(typenps[prop.table_id].c_chinese + '的')
					tableid_of_last_prop = prop.table_id
				c_chinese += name
			if idx + 2 < len(self.np.queried_props):
				c_chinese += '、'
			elif idx + 2 == len(self.np.queried_props):
				c_chinese += '和'
		if self.np.distinct:
			c_chinese += '的全部不同取值'

		if self.np.orderby_props is not None:
			if len(self.np.orderby_props) > 0:
				orderby_props_cc = ''
				for idx, item in enumerate(self.np.orderby_props):
					orderby_props_cc += item.c_chinese.format('')
					if idx + 2 < len(self.np.orderby_props):
						orderby_props_cc += '、'
					elif idx + 2 == len(self.np.orderby_props):
						orderby_props_cc += '和'
				assert self.np.orderby_order is not None
				if self.np.orderby_order == 'asc':
					_order = '升'
				elif self.np.orderby_order == 'desc':
					_order = '降'
				else:
					raise AssertionError
				if self.np.limit is None:
					limit_cc = ''
				else:
					limit_cc = '，只选取最靠前的%d个' % self.np.limit
				c_chinese += '，按%s的%s序排列%s' % (orderby_props_cc, _order, limit_cc)
		else:
			self.np.orderby_props = []

		if self.np.has_union:
			c_chinese = '返回（' + c_chinese + '）中的全部内容和（' + self.np.qrynp_2.c_chinese + '）中的全部内容'
		elif self.np.has_except:
			c_chinese = '返回（' + c_chinese + '）的内容中，除去（' + self.np.qrynp_2.c_chinese + '）之外的部分'
		elif self.np.has_intersect:
			c_chinese = '返回同时在（' + c_chinese + '）和（' + self.np.qrynp_2.c_chinese + '）中的内容'
		return c_chinese

	def process_cc_step_by_step(self, typenps, propertynps, finalize=False):
		c_chinese = []
		sent_1 = 'Result {0[0]}：'

		sent_1 += '从'
		for idx, table_id in enumerate(self.np.table_ids):
			sent_1 += typenps[table_id].c_chinese
			if idx + 2 < len(self.np.table_ids):
				sent_1 += '、'
			elif idx + 2 == len(self.np.table_ids):
				sent_1 += '和'
		sent_1 += '中找出，'

		# queried_props info
		tableid_of_last_prop = None
		# if there are no group-by clauses in this query, write down the ultimate version of queried props directly
		if self.np.group_props is None or len(self.np.group_props) == 0:
			for idx, prop in enumerate(self.np.queried_props):
				# if it is a '*' column
				if isinstance(prop.table_id, list):
					sent_1 += prop.c_chinese
				else:
					if prop.table_id == tableid_of_last_prop:
						name = prop.c_chinese.format('')
					else:
						name = prop.c_chinese.format(typenps[prop.table_id].c_chinese + '的')
						tableid_of_last_prop = prop.table_id
					sent_1 += name
				if idx + 2 < len(self.np.queried_props):
					sent_1 += '、'
				elif idx + 2 == len(self.np.queried_props):
					sent_1 += '和'
		else:
			# if there are group-by clauses in this query, at first we don't add use aggregators, instead we keep all entries
			for idx, prop in enumerate(self.np.queried_props):
				# if it is a '*' column
				if isinstance(prop.table_id, list):
					sent_1 += STAR_PROP.c_chinese
				else:
					if prop.table_id == tableid_of_last_prop:
						name = propertynps[prop.overall_idx].c_chinese.format('')
					else:
						name = propertynps[prop.overall_idx].c_chinese.format(typenps[prop.table_id].c_chinese + '的')
						tableid_of_last_prop = prop.table_id
					sent_1 += name
				if idx + 2 < len(self.np.queried_props):
					sent_1 += '、'
				elif idx + 2 == len(self.np.queried_props):
					sent_1 += '和'
		if self.np.distinct:
			sent_1 += '的全部不同取值'
		c_chinese.append(sent_1)

		# where conditions info
		is_and = None  # whether the condition linker for where conditions is 'and'
		if self.np.cdts is None:
			self.np.cdts = []
		for idx, cond in enumerate(self.np.cdts):
			# allows for 'and' & 'or' linkers both present in a set of 'where' conditions (though not useful as of
			# SPIDER's scope)
			if is_and is None:
				cur_sent = 'Result {0[%d]}：从 Result {0[%d]}中，找出满足' % (
					len(c_chinese), len(c_chinese) - 1)
			else:
				if is_and:
					cur_sent = 'Result {0[%d]}：从Result {0[%d]}中，找出满足' % (
						len(c_chinese), len(c_chinese) - 1)
				else:
					cur_sent = 'Result {0[%d]}：在Result {0[%d]}之余，找出Result {0[%d]}中满足' % (
						len(c_chinese), len(c_chinese) - 1, 0)
			cur_sent += cond.c_chinese
			cur_sent += '的内容'
			if idx < len(self.np.cdts) - 1:
				is_and = (self.np.cdt_linkers[idx] == 'and')  # is_and value may change from True to False
			c_chinese.append(cur_sent)

		# groupby info
		if self.np.group_props is not None:
			if len(self.np.group_props) > 0:
				groupby_sent = 'Result {0[%d]}：从{0[%d]}中，在每个' % (
					len(c_chinese), len(c_chinese) - 1)
				if self.np.having_cdt is not None:
					groupby_sent += '满足'
					groupby_sent += self.np.having_cdt.c_chinese
					groupby_sent += '的、'
				for idx, prop in enumerate(self.np.group_props):
					groupby_sent += prop.c_chinese.format('')
					if idx + 2 < len(self.np.group_props):
						groupby_sent += '、'
					elif idx + 2 == len(self.np.group_props):
						groupby_sent += '和'
				groupby_sent += '的取值下，找出'

				# if there are group-by clauses in query, specify the aggregators of queried props along with the
				# group-by clause itself
				tableid_of_last_prop = None
				for idx, prop in enumerate(self.np.queried_props):
					# if it is a '*' column
					if isinstance(prop.table_id, list):
						groupby_sent += prop.c_chinese
					else:
						if prop.table_id == tableid_of_last_prop:
							name = prop.c_chinese.format('')
						else:
							name = prop.c_chinese.format(typenps[prop.table_id].c_chinese + '的')
							tableid_of_last_prop = prop.table_id
						groupby_sent += name
					if idx + 2 < len(self.np.queried_props):
						groupby_sent += '、'
					elif idx + 2 == len(self.np.queried_props):
						groupby_sent += '和'
				if self.np.distinct:
					groupby_sent += '，找出其所有的不同取值'
				c_chinese.append(groupby_sent)

		if self.np.orderby_props is not None:
			if len(self.np.orderby_props) > 0:
				assert self.np.orderby_order is not None
				if self.np.limit is not None:
					limit_cc = '的前%d个条目顺序' % self.np.limit
				else:
					limit_cc = ''
				if self.np.orderby_order == 'asc':
					_order = '升序'
				elif self.np.orderby_order == 'desc':
					_order = '降序'
				else:
					raise AssertionError
				orderby_sent = 'Result {0[%d]}：将Result {0[%d]}按' % (
					len(c_chinese), len(c_chinese) - 1)
				for idx, item in enumerate(self.np.orderby_props):
					orderby_sent += item.c_chinese.format('')
					if idx + 1 < len(self.np.orderby_props):
						orderby_sent += '、'
				orderby_sent += '的%s排列%s展示' % (_order, limit_cc)
				c_chinese.append(orderby_sent)

		if self.np.has_union or self.np.has_except or self.np.has_intersect:
			second_sents = self.np.qrynp_2.c_chinese_sequence
			len_cur_sents = len(c_chinese)
			len_second_sents = len(second_sents)
			second_sents = ' ### '.join(second_sents)
			second_sents = second_sents.format([('{0[%d]}' % (i + len(c_chinese))) for i in range(len_second_sents)])
			second_sents = second_sents.split(' ### ')
			c_chinese += second_sents
			if self.np.has_union:
				post_clause = 'Result {0[%d]}：返回 Result {0[%d]} 中的所有条目和 Result {0[%d]} 中的所有条目' \
							  % (len(c_chinese), len_cur_sents - 1, len_cur_sents + len_second_sents - 1)
			elif self.np.has_except:
				post_clause = 'Result {0[%d]}：返回 Result {0[%d]} 里面的所有条目中不被 Result {0[%d]} 包含的部分' \
							  % (len(c_chinese), len_cur_sents - 1, len_cur_sents + len_second_sents - 1)
			elif self.np.has_intersect:
				post_clause = 'Result {0[%d]}：返回所有同时在 Result {0[%d]} 和 Result {0[%d]} 中的条目' \
							  % (len(c_chinese), len_cur_sents - 1, len_cur_sents + len_second_sents - 1)
			else:
				raise AssertionError
			c_chinese.append(post_clause)

		# in case of the upper most layer of recursion, finalize the sequence by replacing the '{0[xxx]}' number
		# placeholders with actual numbers 'xxx'
		if finalize:
			total_len = len(c_chinese)
			c_chinese = ' ### '.join(c_chinese)
			c_chinese = c_chinese.format([i for i in range(total_len)])
			c_chinese = c_chinese.split(' ### ')

		return c_chinese


STAR_PROP = PROPERTYNP('everything', '全部信息', '*', 'star', overall_idx=-1, values=[], meta_idx=-1)

CMPERS = [CMP(' is between {0[0]} and {0[1]}', '在{0[0]}和{0[1]}之间', ' between {0[0]} and {0[1]}', 1),
		  CMP(' is {0}', '是{0}', ' = {0}', 2), CMP(' is larger than {0}', '比{0}大', ' > {0}', 3),
		  CMP(' is smaller than {0}', '比{}小', ' < {0}', 4), CMP(' is not smaller than {0}', '不比{0}小', ' >= {0}', 5),
		  CMP(' is not larger than {0}', '不比{0}大', ' <= {0}', 6), CMP(' is not {0}', '不等于{0}', ' != {0}', 7),
		  CMP(' is among {0}', '在{0}之中', ' in {0}', 8), CMP('{0}', '{0}', ' like {0}', 9)]

# these distributions are naturally proportional
num_tables_distribution = {False: transform2distribution_proportional(numpy.array([4361., 3200., 22., 6.])),
						   True: transform2distribution_proportional(numpy.array([459., 51., 1., 0.01]))}
num_wheres_distribution = {False: transform2distribution_proportional(numpy.array([3200., 3000., 600., 400, 1.])),
						   True: transform2distribution_proportional(numpy.array([4., 1.5, 0.2,
																				  0.01, 0.]))}  # padded each number with 10 to allow extreme queries with 4 where-conditions

AGGR_SUBQDIST = transform2distribution_proportional(
	numpy.array([310., 66., 44., 0., 0., 90.]))  # only allow max, min, avg


# type_mat的连接是单向的；prop_mat的连接是双向的，且矩阵是对称的；这里的property不包括*
# is_recursive is False & specific_props is not None	->		是一个union / except / intersect 子语句
def scratch_build(typenps, propertynps, type_mat, prop_mat, prop_rels, is_recursive=False, specific_props=None,
				  print_verbose=False, finalize_sequence=False, cursor=None, require_singlereturn=False):
	res_is_single = False  # initialize result status as not single
	# set random seeds
	random.seed()
	numpy.random.seed()
	total_valid_tables = len(typenps)
	if print_verbose:
		print("-----------")
		print("scratch_build_began")
	# about tables to join
	join_cdts = []
	prior_importance = calc_importance(type_mat, [])
	for tid in range(len(typenps)):
		if typenps[tid].valid is False:
			prior_importance[tid] = -10000
			total_valid_tables -= 1
	num_tables = numpy.random.choice([1, 2, 3, 4], p=num_tables_distribution[is_recursive])
	num_tables = min(num_tables, total_valid_tables)
	# initialize table_distribution with prior distribution; after that, update the distribution
	# according to settled tables.
	table_distribution = transform2distribution(numpy.array(prior_importance, dtype=numpy.float))
	if specific_props is None:
		table_ids = [numpy.random.choice(numpy.arange(len(typenps)), p=table_distribution)]
	else:
		table_ids = []
		contain_star_flag = False
		for prop in specific_props:
			# if the property is a '*' property
			if isinstance(prop.table_id, list):
				contain_star_flag = True
				for item in prop.table_id:
					if item not in table_ids:
						table_ids.append(item)
			else:
				if prop.table_id not in table_ids:
					table_ids.append(prop.table_id)
		# if queried properties contains '*', adding more tables would result in unaligned column numbers between two
		# sides of 'union/except/intersect'
		if contain_star_flag:
			num_tables = len(table_ids)
	initial_length = len(table_ids)
	for _ in range(initial_length, num_tables):
		allow_pseudo_rels = False
		table_importance = calc_importance(type_mat, table_ids, prior_importance)
		for tid in range(len(typenps)):
			if typenps[tid].valid is False:
				prior_importance[tid] = -10000
		table_distribution = transform2distribution(table_importance)
		for idx in range(len(typenps)):
			if idx in table_ids:
				table_distribution[idx] = -10000
		all_zero_flag = True
		for item in table_distribution:
			if item > 0:
				all_zero_flag = False
		if all_zero_flag:
			rho = random.random()
			if rho < 0.5:
				num_tables = _
				table_ids = table_ids[:_]
				break
			else:
				table_distribution = [1] * len(table_distribution)
				allow_pseudo_rels = True
		table_distribution = transform2distribution_proportional(table_distribution)
		new_tid = numpy.random.choice(numpy.arange(len(typenps)), p=table_distribution)
		cur_join_cdt = fetch_join_rel(new_tid, table_ids, prop_rels, typenps, propertynps, allow_pseudo_rels)
		join_cdts.append(cur_join_cdt)
		table_ids.append(new_tid)

	# here it should be guaranteed that each added table should have at least some
	# connected columns with some existing tables (either foreign key or same name)
	table_actived = {}
	for tid in table_ids:
		table_actived[tid] = False

	if print_verbose:
		print("tables set~")

	available_prop_ids = []
	for tabid in table_ids:
		if tabid is None:
			raise AssertionError
		# only add those with actual values instead of None
		for prop_id in typenps[tabid].properties:
			if propertynps[prop_id].valid:
				available_prop_ids.append(prop_id)
	if len(available_prop_ids) == 0:
		raise AssertionError

	# about where conditions
	num_wheres = numpy.random.choice([0, 1, 2, 3, 4], p=num_wheres_distribution[is_recursive])
	where_cdts = []
	where_linkers = []
	where_has_same_entity = False
	# c-v where conditions and c-i where conditions have a proportion of 7 to 1
	where_cnt = 0

	cur_np = NP(prev_np=None, queried_props=[copy.deepcopy(STAR_PROP)], table_ids=table_ids, join_cdts=join_cdts)
	cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps)
	prev_res = cursor.execute(cur_qrynp.z).fetchall()
	ci_occured_flag = False
	_turn_cnter = 0
	while where_cnt < num_wheres:
		_turn_cnter += 1
		if _turn_cnter > 20:
			num_wheres = where_cnt
		if res_is_single:
			num_wheres = where_cnt
			break
		rho = random.random()
		# if already is a recursed function instance, don't dive deeper again
		if rho < 0.15 and is_recursive is False and not ci_occured_flag:
			current_where_cdt = construct_ci_where_cdt(available_prop_ids, typenps, propertynps, type_mat, prop_mat,
													   prop_rels, cursor=cursor)
			if current_where_cdt is not None:
				ci_occured_flag = True
			where_has_same_entity = False
		elif rho < 0.25 and where_cnt == num_wheres - 2:
			current_where_cdt = construct_cv_where_cdt(available_prop_ids, propertynps)
			where_cdts.append(current_where_cdt)
			where_linkers.append('or')
			where_has_same_entity = True
			current_where_cdt = construct_cv_where_cdt(available_prop_ids, propertynps,
													   assigned_prop=current_where_cdt.left)
		elif rho < 0.99:
			current_where_cdt = construct_cv_where_cdt(available_prop_ids, propertynps)
			where_has_same_entity = False
		else:
			current_where_cdt = construct_cc_where_cdt(available_prop_ids, propertynps, prop_mat)
			where_has_same_entity = False
		# there is guaranteed to have a c-v condition
		if current_where_cdt is None:
			current_where_cdt = construct_cv_where_cdt(available_prop_ids, propertynps)
			where_has_same_entity = False
		where_cdts.append(current_where_cdt)

		# set corresponding table_activated to True
		table_actived[current_where_cdt.left.table_id] = True
		if isinstance(current_where_cdt.right, PROPERTYNP):
			table_actived[current_where_cdt.right.table_id] = True

		if where_cnt > 0:
			# choose a linker between 'and' & 'or', with proportion of 511:199 according to SPIDER train set
			rho = random.random()
			if rho < 0.18:
				where_linkers.append('or')
			else:
				where_linkers.append('and')

		# $execution-guidance
		cur_np = NP(prev_np=None, queried_props=[copy.deepcopy(STAR_PROP)], table_ids=table_ids, join_cdts=join_cdts,
					cdts=where_cdts, cdt_linkers=where_linkers)
		cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps)

		res = cursor.execute(cur_qrynp.z).fetchall()
		if len(res) == 1:
			res_is_single = True
		elif len(res) == 0 or len(res) == len(prev_res):
			if where_cnt > 0:
				num_wheres -= 1
			if where_has_same_entity:
				where_cdts = where_cdts[:-2]
			else:
				where_cdts = where_cdts[:-1]
			if where_cnt > 0:
				where_linkers = where_linkers[:-1]
			if where_has_same_entity:
				where_linkers = where_linkers[:-1]
			continue
		# execution-guidance$
		if where_has_same_entity:
			where_cnt += 2
		else:
			where_cnt += 1
		prev_res = res

	if print_verbose:
		print("where set")

	# about group-by and having
	having_cdt = None
	rho = random.random()
	# these probabilities come from SPIDER dataset train set statistics
	if rho < 0.08:
		num_groupbys = 2
	elif rho < 1:
		num_groupbys = 1
	else:
		num_groupbys = 0

	groupable_prop_ids = []
	for prop_id in available_prop_ids:
		if propertynps[prop_id].is_unique is False:
			groupable_prop_ids.append(prop_id)
		else:
			rho = random.random()
			if rho < 0.4:
				groupable_prop_ids.append(prop_id)

	for cond in where_cdts:
		# if the left-side column in this condition is involved in a '=' condition (the aggr for left-side column in
		# where conditions must be empty)
		if cond.cmper.index == 2 and cond.cmper.negative is False:
			# exclude it from groupable_prop_ids since those columns would have only one value left and there'd be no
			# need to group-by
			if cond.left.overall_idx in groupable_prop_ids:
				groupable_prop_ids.remove(cond.left.overall_idx)
			# if the equality condition is imposed on a unique column, then it means there'd be only one value entry
			# in the result altogether, therefore there'd be no need for group-bys or order-bys
			if cond.left.is_unique:
				num_groupbys = 0

	num_groupbys = min(num_groupbys, len(groupable_prop_ids), len(available_prop_ids)-1)

	# if query result contains only one entry, allow no group-by
	if res_is_single:
		num_groupbys = 0

	if num_groupbys > 0:
		groupby_prop_ids, available_after_group_by_prop_ids = choose_groupby_prop(groupable_prop_ids, propertynps,
																				  num_groupbys)
		groupby_prop_ids = groupby_prop_ids.tolist()
		groupby_props = []
		discarded_groupby_propids = []
		for i, idx in enumerate(groupby_prop_ids):
			# $execution-guidance
			_prop = copy.deepcopy(STAR_PROP)
			_prop.set_aggr(3)
			cur_np = NP(prev_np=None, queried_props=[_prop], table_ids=table_ids, join_cdts=join_cdts,
						cdts=where_cdts, cdt_linkers=where_linkers,
						group_props=groupby_props + [copy.deepcopy(propertynps[idx])], having_cdt=None)
			cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps)
			res = cursor.execute(cur_qrynp.z).fetchall()
			all_one = True
			for item in res:
				if item[0] != 1:
					all_one = False
					break
			# if there are no more than 1 value after 'group by' or each group have only one value
			if len(res) <= 1 or all_one:
				discarded_groupby_propids.append(idx)
			else:
				# execution-guidance$
				groupby_props.append(copy.deepcopy(propertynps[idx]))
		for pid in discarded_groupby_propids:
			groupby_prop_ids.remove(pid)
		available_after_group_by_prop_ids = find_available_propids_after_groupby(propertynps, groupby_prop_ids)
		num_groupbys = len(groupby_prop_ids)

		if num_groupbys == 0:
			groupby_prop_ids = None
			available_after_group_by_prop_ids = None
		else:
			# set corresponding table_activated to True
			for prop in groupby_props:
				table_actived[prop.table_id] = True

			# from statistics we also know that more than one 'having' conditions need not be considered
			rho = random.random()
			having_usable_prop_ids = []
			for idx in available_prop_ids:
				if idx not in groupby_prop_ids:
					having_usable_prop_ids.append(idx)
			if rho < 0.03:
				having_cdt = construct_ci_where_cdt(having_usable_prop_ids, typenps, propertynps, type_mat, prop_mat,
													prop_rels, True, cursor=cursor, no_negative=True)
			elif rho < 0.15:
				having_cdt = construct_cv_where_cdt(having_usable_prop_ids, propertynps, True, no_negative=True)
			elif rho < 0.4:
				_star = copy.deepcopy(STAR_PROP)
				_star.set_aggr(3)
				having_cdt = construct_cv_where_cdt([], propertynps, True, _star, no_negative=True)

			# if all groups or no groups are excluded after this 'having_cdt', then don't add this 'having_cdt'
			_prop = copy.deepcopy(STAR_PROP)
			_prop.set_aggr(3)
			prev_np = NP(prev_np=None, queried_props=[_prop], table_ids=table_ids, join_cdts=join_cdts,
						cdts=where_cdts, cdt_linkers=where_linkers,
						group_props=groupby_props, having_cdt=having_cdt)
			prev_qrynp = QRYNP(prev_np, typenps=typenps, propertynps=propertynps)
			prev_res = cursor.execute(prev_qrynp.z).fetchall()
			cur_np = NP(prev_np=None, queried_props=[_prop], table_ids=table_ids, join_cdts=join_cdts,
						cdts=where_cdts, cdt_linkers=where_linkers,
						group_props=groupby_props, having_cdt=having_cdt)
			cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps)
			res = cursor.execute(cur_qrynp.z).fetchall()
			if len(res) == 0 or len(res) == len(prev_res):
				if len(res) == len(prev_res):
					pass
				having_cdt = None

			# set corresponding table_activated to True
			if having_cdt is not None:
				table_actived[having_cdt.left.table_id] = True
	else:
		groupby_prop_ids = None
		groupby_props = []
		available_after_group_by_prop_ids = None

	if print_verbose:
		print("group-by set~")

	rho = random.random()
	if specific_props is not None:
		props2query = []
		for prop in specific_props:
			assert (isinstance(prop, PROPERTYNP))
			prop = copy.deepcopy(prop)
			if groupby_prop_ids is not None and prop.overall_idx not in available_after_group_by_prop_ids and prop.dtype != 'star':
				# if the specified prop is already aggregated, just keep that aggregator
				if prop.aggr != 0:
					pass
				elif prop.dtype in SUBTRACTABLE_DTYPES:
					probs = copy.deepcopy(AGGR_DISTS[prop.dtype])
					probs[3] = 0
					probs = transform2distribution_proportional(probs)
					aggr_id = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=probs)
					prop.set_aggr(aggr_id)
				else:
					# if columns which must be aggregated due to group-by cannot be aggregated due to its being a
					# specified prop, then delete the group-by clause
					groupby_prop_ids = None
					groupby_props = []
					available_after_group_by_prop_ids = None
					having_cdt = None
			props2query.append(prop)
	elif rho < 0.05:
		props2query = [copy.deepcopy(STAR_PROP)]
		props2query[0].table_id = table_ids
	else:
		num_props2query = min(math.ceil(abs(random.gauss(0, 1))), len(available_prop_ids))
		query_probabilities = calc_forquery_distribution(available_prop_ids, groupby_prop_ids, propertynps)
		propids2query = []
		if groupby_prop_ids is not None and len(groupby_prop_ids) > 0:
			rho = random.random()
			if rho < 0.8:
				mandatory_id = random.choice(groupby_prop_ids)
				propids2query.append(mandatory_id)
				query_probabilities[mandatory_id] = 0
				num_props2query -= 1

		# if a column's value is already settled by an equality 'where' condition, then there is no need to query it
		# anymore, since it's something we already know before our query.
		for cdt in where_cdts:
			if cdt.cmper.index == 2:
				query_probabilities[cdt.left.overall_idx] = 0.000001
		query_probabilities = transform2distribution_proportional(query_probabilities)

		propids2query += numpy.random.choice(numpy.arange(len(propertynps)), num_props2query, replace=False,
											p=query_probabilities).tolist()
		num_props2query = len(propids2query)
		for i in propids2query:
			assert (i in available_prop_ids)
			# set corresponding table_activated to True
			table_actived[propertynps[i].table_id] = True

		# if no props are specified, '*' is not the only queried prop, and there are tables not attended to up till
		# now, add a random column from that table to queried-props so that it can get involved
		for key in table_actived:
			if table_actived[key] is False:
				additional_props_to_select = typenps[key].properties
				propids2query.append(numpy.random.choice(additional_props_to_select))
		props2query = []
		for idx in propids2query:
			chosen_prop = copy.deepcopy(propertynps[idx])
			rho = random.random()
			if groupby_prop_ids is not None and idx not in available_after_group_by_prop_ids:
				aggr_id = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=AGGR_DISTS[chosen_prop.dtype])
				chosen_prop.set_aggr(aggr_id)
			elif groupby_prop_ids is None and rho < 0.4:

				# if there is only one value for this column in query, then we only by probability of 0.05 use 'count()'
				cur_np = NP(prev_np=None, queried_props=[copy.deepcopy(chosen_prop)], table_ids=table_ids, join_cdts=join_cdts,
							cdts=where_cdts, cdt_linkers=where_linkers,
							group_props=groupby_props, having_cdt=having_cdt)
				cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps)
				res = cursor.execute(cur_qrynp.z).fetchall()

				if len(res) > 1 or rho < 0.05:
					aggr_id = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=AGGR_DISTS[chosen_prop.dtype])
					chosen_prop.set_aggr(aggr_id)
			props2query.append(chosen_prop)

		if rho < 0.15:
			props2query.pop()
			star = copy.deepcopy(STAR_PROP)
			star.table_id = table_ids
			rho = random.random()
			# for queries with group-by, count aggregator has to be added
			if rho < 0.9 or groupby_prop_ids is not None:
				star.set_aggr(3)
			props2query.append(star)

	if print_verbose:
		print("properties to query set")

	if groupby_prop_ids is None:
		props2query_covered_by_groupbyids = False
	else:
		props2query_covered_by_groupbyids = True
		for prop in props2query:
			if prop.overall_idx not in groupby_prop_ids:
				props2query_covered_by_groupbyids = False

	# check if all selected values are aggregated, if so, allow no more 'orderby count(*)'
	all_aggregated = True
	for prop in props2query:
		if prop.aggr == 0:
			all_aggregated = False
			break

	# about order by; no order-by for recursed sub-queries
	rho = abs(random.gauss(0, 1))

	if require_singlereturn and props2query[0].aggr == 0:
		assert is_recursive
		num_orderbys = 1
	elif is_recursive:
		num_orderbys = 0
	elif rho > 3.4:
		num_orderbys = int(rho)  # allow for a tiny possibility of having more than 3 orderby properties
	elif rho > 2.6:
		num_orderbys = 2
	elif rho > 0.8:
		num_orderbys = 1
	else:
		num_orderbys = 0

	need_orderby_covered = False
	# if groupBy is not used by 'having', and xxx is covered by groupBy columns, then use an grouped-columns related
	# orderBy to use it
	if having_cdt is None and num_groupbys > 0 and props2query_covered_by_groupbyids:
		num_orderbys = max(1, num_orderbys)
		need_orderby_covered = True

	orderby_available_props = []
	if specific_props is None or is_recursive:
		for prop_id in available_prop_ids:
			prop = copy.deepcopy(propertynps[prop_id])
			if prop.dtype == 'star':
				continue
			# if it's not a query with group-by and this column queried is with aggregator, this column is excluded
			# from consideration of order-by since there can only be one value for this column queried
			veto = False
			for cp in props2query:
				if cp.overall_idx == prop_id:
					if num_groupbys == 0 and cp.aggr != 0:
						veto = True
					else:
						prop = copy.deepcopy(cp)
					break
			if veto:
				continue
			if prop.dtype in ORDERBY_DTYPES:
				# if all returned entries are the same, don't order by this column
				cur_np = NP(prev_np=None, queried_props=props2query, table_ids=table_ids, join_cdts=join_cdts,
								cdts=where_cdts, cdt_linkers=where_linkers, group_props=groupby_props,
								having_cdt=having_cdt)
				cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps, finalize_sequence=finalize_sequence)
				res = cursor.execute(cur_qrynp.z).fetchall()
				if not all_the_same(res):
					orderby_available_props.append(prop)
	else:
		for prop in props2query:
			if prop.dtype == 'star':
				continue
			if num_groupbys == 0 and prop.aggr != 0:
				continue

			# if all returned entries are the same, don't order by this column
			cur_np = NP(prev_np=None, queried_props=props2query, table_ids=table_ids, join_cdts=join_cdts,
						cdts=where_cdts, cdt_linkers=where_linkers, group_props=groupby_props,
						having_cdt=having_cdt)
			cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps, finalize_sequence=finalize_sequence)
			res = cursor.execute(cur_qrynp.z).fetchall()
			if not all_the_same(res):
				orderby_available_props.append(copy.deepcopy(prop))

	for cond in where_cdts:
		# if the left-side column in this condition is involved in a '=' condition (the aggr for left-side column in
		# where conditions must be empty)
		if cond.cmper.index == 2 and cond.cmper.negative is False:
			# exclude it from groupable_prop_ids since those columns would have only one value left and there'd be no
			# need to group-by
			for prop in orderby_available_props:
				if cond.left.overall_idx == prop.overall_idx:
					orderby_available_props.remove(prop)
			# if the equality condition is imposed on a unique column, then it means there'd be only one value entry
			# in the result altogether, therefore there'd be no need for group-bys or order-bys
			if cond.left.is_unique:
				num_orderbys = 0

	num_orderbys = min(num_orderbys, len(orderby_available_props))

	limit = None
	orderby_order = None
	orderby_props = None
	# no order-by for 'in' sub-queries
	if num_orderbys > 0:
		# order-by properties are barely relevant to group-by columns, on the other hand,
		# they are to around 25% relevant to selected columns

		# here larger probability of being picked to order-by is assigned to those 'select'ed in query
		ob_probs = [1]*len(orderby_available_props)
		for i, p1 in enumerate(orderby_available_props):
			for p2 in props2query:
				if p1.overall_idx == p2.overall_idx:
					ob_probs[i] += 1
		ob_probs = transform2distribution_proportional(ob_probs)
		orderby_props_raw = numpy.random.choice(orderby_available_props, num_orderbys, p=ob_probs, replace=False)

		orderby_props = []
		if need_orderby_covered:
			orderby_cover_satisfied = False
		else:
			orderby_cover_satisfied = None
		for prop in orderby_props_raw:
			prop = copy.deepcopy(prop)
			# if group-by involved queries have queried props, their prop.aggr != 0, hence those props should not be
			# added more aggrs
			if groupby_prop_ids is not None and prop.overall_idx not in available_after_group_by_prop_ids and prop.aggr == 0:
				aggr_id = numpy.random.choice(numpy.arange(len(AGGREGATION_FUNCTIONS)), p=AGGR_DISTS[prop.dtype])
				prop.set_aggr(aggr_id)
				# if there are orderby columns not in group-by columns, then no extra columns to order by is needed
				orderby_cover_satisfied = True
			orderby_props.append(prop)

		# with a 0.3 probability or is is needed, add a STAR property as orderby-property in order to
		rho = random.random()
		if (rho < 0.9 and num_groupbys > 0) or (
				rho < 0.9 and orderby_cover_satisfied) or orderby_cover_satisfied == False:
			# if it is a union/except/intersect clause, allow only queried props to be ordered, care about usefulness
			# of group-by clauses no more here
			if specific_props is None and not all_aggregated:
				orderby_props.pop()
				_star = copy.deepcopy(STAR_PROP)
				_star.set_aggr(3)
				orderby_props.append(_star)

		rho = random.random()
		if rho < 0.368:
			orderby_order = 'asc'
		else:
			orderby_order = 'desc'

		rho = random.random()
		if require_singlereturn:
			limit = 1
		elif rho < 0.676:
			limit_dist = [0] + [0.05] * 100
			limit_dist[1] = 90
			limit_dist[2] = 2
			limit_dist[3] = 5
			limit_dist[5] = 2
			limit_dist[10] = 1
			for idx in range(5, 101, 5):
				limit_dist[idx] += 0.05
			for idx in range(10, 101, 10):
				limit_dist[idx] += 0.1

			cur_np = NP(prev_np=None, queried_props=props2query, table_ids=table_ids, join_cdts=join_cdts,
						cdts=where_cdts, cdt_linkers=where_linkers, group_props=groupby_props,
						having_cdt=having_cdt)
			cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps, finalize_sequence=finalize_sequence)
			res = cursor.execute(cur_qrynp.z).fetchall()
			limit_dist = limit_dist[:len(res)+1]

			limit = random.choices(range(min(len(res)+1, 101)), weights=limit_dist)[0]
		else:
			limit = None

	if print_verbose:
		print("order-by set~")

	rho = random.random()
	np_2 = None
	qrynp_2 = None
	has_union = None
	has_except = None
	has_intersect = None
	if rho < 0.15 and not is_recursive and specific_props is None and orderby_props is None:
		flag = True
		for prop in props2query:
			if prop.aggr != 0:
				flag = False
				break
		# if no aggregators exist in queried properties
		if flag:
			# here because the assigned properties might not be compatible with group-by clauses or such, it might not
			# run, if it doesn't run, just discard it
			np_2, qrynp_2 = scratch_build(typenps, propertynps, type_mat, prop_mat, prop_rels, is_recursive=False,
										  specific_props=props2query, cursor=cursor, print_verbose=print_verbose)

			# choose between using the second query as an 'union' or an 'except'
			rho = random.random()
			if rho < 0.1:
				has_union = True
			elif rho < 0.5:
				has_intersect = True
			else:
				has_except = True

	if np_2 is not None:
		assert qrynp_2 is not None
		cur_np = NP(prev_np=None, queried_props=props2query, table_ids=table_ids, join_cdts=join_cdts,
						cdts=where_cdts, cdt_linkers=where_linkers, group_props=groupby_props, having_cdt=having_cdt,
						orderby_props=orderby_props, orderby_order=orderby_order, limit=limit)
		cur_qrynp = QRYNP(cur_np, typenps=typenps, propertynps=propertynps, finalize_sequence=finalize_sequence)
		res_1 = cursor.execute(cur_qrynp.z).fetchall()
		res_2 = cursor.execute(qrynp_2.z).fetchall()
		if either_contain(res_1, res_2):
			np_2 = None
			qrynp_2 = None
			has_union = False
			has_intersect = False
			has_except = False

	if print_verbose:
		print("post-subquery set~")

	inspect_np = NP(prev_np=None, queried_props=props2query, table_ids=table_ids, join_cdts=join_cdts,
					cdts=where_cdts, cdt_linkers=where_linkers, group_props=groupby_props, having_cdt=having_cdt,
					orderby_props=orderby_props, orderby_order=orderby_order, limit=limit, np_2=np_2, qrynp_2=qrynp_2,
					has_union=has_union, has_except=has_except, has_intersect=has_intersect)
	inspect_qrynp = QRYNP(inspect_np, typenps=typenps, propertynps=propertynps, finalize_sequence=finalize_sequence)
	res = cursor.execute(inspect_qrynp.z).fetchall()
	if len(res) > 200:
		DISTINCT_PROB = 0.2
	elif is_unique(res):
		DISTINCT_PROB = 0.1
	else:
		DISTINCT_PROB = 0.2
	rho = random.random()
	if rho < DISTINCT_PROB:
		distinct = True
	else:
		distinct = False
	final_np = NP(prev_np=None, queried_props=props2query, table_ids=table_ids, join_cdts=join_cdts,
				  cdts=where_cdts, cdt_linkers=where_linkers, group_props=groupby_props, having_cdt=having_cdt,
				  orderby_props=orderby_props, orderby_order=orderby_order, limit=limit, np_2=np_2, qrynp_2=qrynp_2,
				  has_union=has_union, has_except=has_except, has_intersect=has_intersect, distinct=distinct)
	final_qrynp = QRYNP(final_np, typenps=typenps, propertynps=propertynps, finalize_sequence=finalize_sequence)
	if print_verbose:
		print("ALL SET!")
		print("-----------")
	return final_np, final_qrynp


def build_spider_dataset(num):
	valid = True  # if there exists empty columns in the database, then the database is assumed invalid, reported
	# and discarded
	with open(TABLE_MATADATA_PATH, 'r') as fp:
		json_file = json.load(fp)
	meta = json_file[num]
	database_name = DATABASE_PATH + '/%s/%s.sqlite' % (meta['db_id'], meta['db_id'])
	print(meta['db_id'])
	propertynps = []
	# disgard the '*'
	for idx, prop_name in enumerate(meta['column_names']):
		table_idx = prop_name[0]
		if table_idx < 0:
			# print('star: ', idx, prop_name)
			continue
		c_english = '{0}$' + prop_name[1] + '$'
		c_chinese = '{0}$' + prop_name[1] + '$'
		col_z = meta['column_names_original'][idx][1]
		# if the name contains ' ', wrap it with brackets
		if ' ' in col_z:
			col_z = '[' + col_z + ']'
		z = '{0}%s' % col_z
		dtype = meta['column_types'][idx]
		propertynps.append(
			PROPERTYNP(c_english=c_english, c_chinese=c_chinese, z=z, dtype=dtype, table_id=table_idx,
					   overall_idx=idx - 1, meta_idx=idx - 1))

	typenps = []
	for idx, tab_name in enumerate(meta['table_names']):
		c_english = '@'+tab_name+'@'
		c_chinese = '@'+tab_name+'@'
		z = meta['table_names_original'][idx]
		if ' ' in z:
			z = '[' + z + ']'
		properties = []
		for prop_idx, prop_ori in enumerate(meta['column_names']):
			if prop_ori[0] == idx:
				# '*' disgarded at generation time
				properties.append(prop_idx - 1)
		typenps.append(TYPENP(c_english=c_english, c_chinese=c_chinese, z=z, overall_idx=idx, properties=properties))

	fks = meta['foreign_keys']  # a.k.a the prop_rels
	for pair in fks:
		if meta['column_names'][pair[0]][0] == meta['column_names'][pair[1]][0]:
			new_typenp = copy.deepcopy(typenps[meta['column_names'][pair[0]][0]])
			new_typenp.overall_idx = len(typenps)
			new_typenp.properties = []
			for pid in typenps[meta['column_names'][pair[0]][0]].properties:
				new_prop = copy.deepcopy(propertynps[pid])
				new_prop.table_id = new_typenp.overall_idx
				new_prop.overall_idx = len(propertynps)
				new_typenp.properties.append(new_prop.overall_idx)
				propertynps.append(new_prop)
				propertynps[pid].clones.append(new_prop.overall_idx)
			typenps.append(new_typenp)
			typenps[meta['column_names'][pair[0]][0]].clones.append(new_typenp.overall_idx)

	# here they're both directioned
	fk_type_matrix = [[0] * len(typenps) for i in range(len(typenps))]
	fk_property_matrix = [[0] * len(propertynps) for i in range(len(propertynps))]

	for pair in fks:
		if meta['column_names'][pair[0]][0] == meta['column_names'][pair[1]][0]:
			tid = meta['column_names'][pair[0]][0]
			for i, clone_id in enumerate(typenps[tid].clones):
				fk_type_matrix[tid][clone_id] += 1
				fk_property_matrix[pair[0] - 1][propertynps[pair[1] - 1].clones[i]] += 1
				fk_property_matrix[propertynps[pair[0] - 1].clones[i]][pair[1] - 1] += 1
		fk_property_matrix[pair[0] - 1][pair[1] - 1] += 1
		fk_type_matrix[meta['column_names'][pair[0]][0]][meta['column_names'][pair[1]][0]] += 1
	# PROBABLY BRING THE NAME MATCHING INTO ACCOUNT?
	nm_type_matrix = [[0] * len(typenps) for i in range(len(typenps))]
	nm_property_matrix = [[0] * len(propertynps) for i in range(len(propertynps))]
	for i in range(len(propertynps)):
		for j in range(len(propertynps)):
			if propertynps[i].table_id in typenps[propertynps[j].table_id].clones or propertynps[j].table_id in typenps[
				propertynps[i].table_id].clones:
				continue
			if propertynps[i].z.format('') == propertynps[j].z.format(''):
				if propertynps[i].z.format('').lower() == 'id' and propertynps[i].overall_idx != propertynps[
					j].overall_idx \
						and propertynps[i].overall_idx not in propertynps[j].clones \
						and propertynps[j].overall_idx not in propertynps[i].clones:
					continue
				nm_property_matrix[i][j] += 1 * NAME_PAIR_WEIGHT
				nm_property_matrix[j][i] += 1 * NAME_PAIR_WEIGHT
				nm_type_matrix[propertynps[i].table_id][propertynps[j].table_id] += 1 * NAME_PAIR_WEIGHT
				nm_type_matrix[propertynps[j].table_id][propertynps[i].table_id] += 1 * NAME_PAIR_WEIGHT

	conn = sqlite3.connect(database_name)
	# conn.create_function('FIXENCODING', 1, lambda s: str(s).encode('latin_1'))
	crsr = conn.cursor()

	for prop in propertynps:
		# if prop.dtype == 'varchar(1000)':
		#	conn.execute('UPDATE "{0}" SET "{1}" = FIXENCODING("{1}")'.format(typenps[prop.table_id].z, prop.z.format('')))
		query_all = 'select %s from %s' % (prop.z.format(''), typenps[prop.table_id].z)
		try:
			all_values = crsr.execute(query_all).fetchall()
		except Exception as e:
			print(e)
			print(query_all)
			raise
		# if a property is empty before discarding invalid values, it means whole tables have no entries, assume as
		# invalid database
		if len(all_values) == 0:
			print("Empty property: ", prop.z.format(typenps[prop.table_id].z))
			valid = False
		if len(all_values) > MAX_VALUE_ENTRIES:
			all_values = random.choices(all_values, k=MAX_VALUE_ENTRIES)

		temp_all_values = []
		for idx, item in enumerate(all_values):
			if isinstance(item, tuple) or isinstance(item, list):
				assert (len(item) == 1)
				item = item[0]
			# if isinstance(item, bytes):
			#	item = item.decode('latin_1')
			try:
				item_str = str(item)
			except Exception as e:
				print("!")
				item_str = item
			if prop.dtype in ['datetime', 'bool']:
				item_str = "'" + item_str + "'"

			# do not save those None or '' values to avoid confusion
			if item is None or item == '':
				continue
			temp_all_values.append(
				VALUENP(c_english=item_str, c_chinese=item_str, z=item_str, dtype=prop.dtype))

		# if prop.dtype == 'bool':
		#	print(all_values)
		all_values = temp_all_values
		if is_unique(all_values):
			prop.is_unique = True

		prop.set_values(all_values)

	for idx in range(len(typenps)):
		type_valid = False
		for pid in typenps[idx].properties:
			if propertynps[pid].valid is True:
				type_valid = True
		if not type_valid:
			typenps[idx].valid = False

	type_matrix = [[0] * len(typenps) for i in range(len(typenps))]
	for i in range(len(type_matrix)):
		for j in range(len(type_matrix[0])):
			type_matrix[i][j] = fk_type_matrix[i][j] + nm_type_matrix[i][j]

	property_matrix = [[0] * len(propertynps) for i in range(len(propertynps))]
	for i in range(len(property_matrix)):
		for j in range(len(property_matrix)):
			property_matrix[i][j] = fk_property_matrix[i][j] + nm_property_matrix[i][j]

	property_matrix_np = numpy.matrix(property_matrix)
	property_scores = pagerank_scores(property_matrix_np)
	# print(property_matrix)
	# print("")
	# print(property_scores)
	for i in range(len(property_matrix)):
		coefficient = property_scores[i] / float(sum(property_matrix[i]))
		for j in range(len(property_matrix)):
			property_matrix[i][j] = coefficient * property_matrix[i][j]

	# turn the property_matrix un-directioned
	for i in range(len(property_matrix)):
		for j in range(len(property_matrix)):
			property_matrix[i][j] += property_matrix[j][i]
	fk_prop_rels = []
	for pair in fks:
		if propertynps[pair[0] - 1].table_id == propertynps[pair[1] - 1].table_id:
			tid = propertynps[pair[0] - 1].table_id
			for i, clone_id in enumerate(typenps[tid].clones):
				fk_prop_rels.append(
					PROP_REL(pair[0] - 1, propertynps[pair[1] - 1].clones[i], tid,
							 clone_id,
							 property_matrix[pair[0] - 1][propertynps[pair[1] - 1].clones[i]]))
				fk_prop_rels.append(
					PROP_REL(propertynps[pair[0] - 1].clones[i], pair[1] - 1, clone_id,
							 tid,
							 property_matrix[propertynps[pair[0] - 1].clones[i]][pair[1] - 1]))
		fk_prop_rels.append(
			PROP_REL(pair[0] - 1, pair[1] - 1, propertynps[pair[0] - 1].table_id, propertynps[pair[1] - 1].table_id,
					 property_matrix[pair[0] - 1][pair[1] - 1]))

	nm_prop_rels = []
	for prop1 in propertynps:
		for prop2 in propertynps:
			if prop1.table_id in typenps[prop2.table_id].clones or prop2.table_id in typenps[prop1.table_id].clones or prop1.overall_idx == prop2.overall_idx:
				continue
			if prop1.z == prop2.z:
				# exclude those 'id' queries which are not in the same query
				if prop1.z.format('').lower() == 'id' and prop1.overall_idx != prop2.overall_idx \
						and prop1.overall_idx not in prop2.clones and prop2.overall_idx not in prop1.clones:
					continue
				nm_prop_rels.append(PROP_REL(prop1.overall_idx, prop2.overall_idx, prop1.table_id, prop2.table_id,
											 property_matrix[prop1.overall_idx][prop2.overall_idx] * NAME_PAIR_WEIGHT))
	prop_rels = fk_prop_rels + nm_prop_rels
	type_matrix = numpy.matrix(type_matrix)
	property_matrix = numpy.matrix(property_matrix)

	for p in propertynps:
		if p.values is None:
			print(p.z)
			raise AssertionError
		if len(p.values) == 0:
			p.valid = False
	print("Finished resolving database $ %s $" % meta['db_id'])

	num_queries = calc_num_queries_via_stats(len(fk_prop_rels))
	return database_name, meta[
		'db_id'], typenps, propertynps, type_matrix, property_matrix, prop_rels, valid, conn, crsr, num_queries


def format_sql_spider(np):
	res = {}
	if np.has_except is True:
		res['except'] = format_sql_spider(np.np_2)
		res['union'] = None
		res['intersect'] = None
	elif np.has_union is True:
		res['except'] = None
		res['union'] = format_sql_spider(np.np_2)
		res['intersect'] = None
	elif np.has_intersect is True:
		res['except'] = None
		res['union'] = None
		res['intersect'] = format_sql_spider(np.np_2)
	else:
		res['except'] = None
		res['union'] = None
		res['intersect'] = None

	res['from'] = {}
	conds = []
	table_units = []
	for item in np.join_cdts:
		assert item.cmper.negative is False
		assert int(item.left.aggr) == 0
		assert int(item.right.aggr) == 0
		conds.append(
			[False, item.cmper.index, [0, [0, item.left.meta_idx + 1, False], None],
			 [0, item.right.meta_idx + 1, False], None])
	for item in np.table_ids:
		table_units.append(['table_unit', int(item)])
	res['from']['conds'] = conds
	res['from']['table_units'] = table_units

	res['groupBy'] = []
	for item in np.group_props:
		res['groupBy'].append([0, item.meta_idx + 1, False])
	if np.having_cdt is not None:
		assert np.having_cdt.cmper.negative is False
		hvg = [False, np.having_cdt.cmper.index, [0, [int(np.having_cdt.left.aggr), np.having_cdt.left.meta_idx + 1,
													  np.having_cdt.left.distinct], None]]
		# condition type must be  either cv or ci
		if isinstance(np.having_cdt.right, list) or isinstance(np.having_cdt.right, numpy.ndarray):
			if len(np.having_cdt.right) == 1:
				if np.having_cdt.left.dtype in ['int', 'star']:
					hvg.append(int(float(np.having_cdt.right[0].z)))
				elif np.having_cdt.left.dtype == 'double':
					hvg.append(float(np.having_cdt.right[0].z))
				else:
					hvg.append(np.having_cdt.right[0].z)
				hvg.append(None)
			else:
				assert (len(np.having_cdt.right) == 2)
				if np.having_cdt.left.dtype in ['int', 'star']:
					hvg.append(int(float(np.having_cdt.right[0].z)))
					hvg.append(int(float(np.having_cdt.right[1].z)))
				elif np.having_cdt.left.dtype == 'double':
					hvg.append(float(np.having_cdt.right[0].z))
					hvg.append(float(np.having_cdt.right[1].z))
				else:
					hvg.append(np.having_cdt.right[0].z)
					hvg.append(np.having_cdt.right[1].z)
		else:
			assert (isinstance(np.having_cdt.right, QRYNP))
			hvg.append(format_sql_spider(np.having_cdt.right.np))
			hvg.append(None)
		res['having'] = [hvg]
	else:
		res['having'] = []

	if np.limit is not None:
		res['limit'] = int(np.limit)
	else:
		res['limit'] = None

	if np.orderby_order is None:
		res['orderBy'] = []
	else:
		res['orderBy'] = [np.orderby_order]
		orderby_proplist = []
		for prop in np.orderby_props:
			orderby_proplist.append([0, [int(prop.aggr), prop.meta_idx + 1, False], None])
		res['orderBy'].append(orderby_proplist)

	res['select'] = [np.distinct]
	queried_proplist = []
	for prop in np.queried_props:
		queried_proplist.append([int(prop.aggr), [0, [0, prop.meta_idx + 1, prop.distinct], None]])
	res['select'].append(queried_proplist)
	'''
	try:
		string = json.dumps(res)
	except Exception as e:
		raise AssertionError
	'''
	res['where'] = []
	for cond_idx, cond in enumerate(np.cdts):
		# convert the condition into a form of list same as SPIDER
		listed_cond = [cond.cmper.negative, cond.cmper.index,
					   [0, [0, cond.left.meta_idx + 1, False], None]]
		if isinstance(cond.right, QRYNP):
			listed_cond.append(format_sql_spider(cond.right.np))
			listed_cond.append(None)
		elif isinstance(cond.right, PROPERTYNP):
			listed_cond.append([0, [0, cond.right.meta_idx + 1, False], None])
			listed_cond.append(None)
		else:
			if not isinstance(cond.right, list) and not isinstance(cond.right, numpy.ndarray):
				print(cond.right)
				raise AssertionError
			if len(cond.right) == 1:
				if cond.left.dtype in ['int', 'star']:
					listed_cond.append(int(float(cond.right[0].z)))
				elif cond.left.dtype == 'double':
					listed_cond.append(float(cond.right[0].z))
				else:
					listed_cond.append(cond.right[0].z)
				listed_cond.append(None)
			elif len(cond.right) == 2:
				if cond.left.dtype in ['int', 'star']:
					listed_cond.append(int(float(cond.right[0].z)))
					listed_cond.append(int(float(cond.right[1].z)))
				elif cond.left.dtype == 'double':
					listed_cond.append(float(cond.right[0].z))
					listed_cond.append(float(cond.right[1].z))
				else:
					listed_cond.append(cond.right[0].z)
					listed_cond.append(cond.right[1].z)
			else:
				raise AssertionError
		res['where'].append(listed_cond)
		if cond_idx < len(np.cdt_linkers):
			res['where'].append(np.cdt_linkers[cond_idx])
	return res


def format_query_to_spider(np, qrynp, database_name, sample, headers):
	qry_formatted = {}
	qry_formatted['db_id'] = database_name
	qry_formatted['query'] = qrynp.z
	qry_formatted['query_toks'] = qrynp.z_toks
	qry_formatted['query_toks_no_value'] = qrynp.z_toks_novalue
	qry_formatted['question'] = qrynp.c_english
	qry_formatted['question_toks'] = qrynp.c_english.split()
	for idx in range(len(qry_formatted['question_toks'])):
		qry_formatted['question_toks'][idx] = qry_formatted['question_toks'][idx].strip('$')
	qry_formatted['question_sequence'] = qrynp.c_english_sequence
	qry_formatted['question_sequence_toks'] = [item.split() for item in qrynp.c_english_sequence]
	qry_formatted['question_chinese'] = qrynp.c_chinese
	qry_formatted['question_toks_chinese'] = chinese_split_words(qrynp.c_chinese)
	qry_formatted['question_sequence_chinese'] = qrynp.c_chinese_sequence
	qry_formatted['questions_sequence_toks_chinese'] = [chinese_split_words(item) for item in qrynp.c_chinese_sequence]
	qry_formatted['sql'] = format_sql_spider(np)
	serialized_sample = [', '.join(headers)]
	for s in sample:
		assert len(s) == len(headers)
		serialized_s = []
		for c in s:
			try:
				serialized_s.append(str(c))
			except Exception as e:
				serialized_s.append('#Unsupported#')
		serialized_sample.append(', '.join(serialized_s))
	qry_formatted['answer_sample'] = serialized_sample
	assert 'limit' in qry_formatted['sql']
	return qry_formatted


def generate_queries(database_idx):
	database_path, database_name, typenps, propertynps, type_matrix, property_matrix, prop_rels, valid_database, conn, crsr, num_queries = build_spider_dataset(
		database_idx)
	if not valid_database:
		return [], [], [], [], [], []

	saved_results = []
	dumped_results = []
	saved_gold = []
	dumped_gold = []
	saved_canonical = []
	dumped_canonical = []
	if not os.path.isdir(SAVE_PATH + database_name + '/'):
		os.makedirs(SAVE_PATH + database_name + '/')
	saved_gold_path = SAVE_PATH + database_name + '/gold_saved.sql'
	dumped_gold_path = SAVE_PATH + database_name + '/gold_dumped.sql'
	saved_canonical_path = SAVE_PATH + database_name + '/canonical_saved.txt'
	dumped_canonical_path = SAVE_PATH + database_name + '/canonical_dumped.txt'
	saved_gold_fp = open(saved_gold_path, 'w')
	dumped_gold_fp = open(dumped_gold_path, 'w')
	saved_canonical_fp = open(saved_canonical_path, 'w')
	dumped_canonical_fp = open(dumped_canonical_path, 'w')
	error_logfile = open(SAVE_PATH + database_name + '/error.log', 'w')
	print('total number: ', num_queries)
	for query_idx in range(num_queries):
		if query_idx % 10 == 0:
			print(query_idx)
		should_dump = False
		np, qrynp = scratch_build(typenps, propertynps, type_matrix, property_matrix, prop_rels, finalize_sequence=True,
								  cursor=crsr)
		try:
			qry_returned = crsr.execute(qrynp.z).fetchall()
		except sqlite3.OperationalError as e:
			error_logfile.write('SQL line: ' + qrynp.z + '\n' + 'Error message: ' + str(e) + '\n\n')
			print("!!!: ", qrynp.z, ';\t', e)
			qry_returned = []

		if len(qry_returned) == 0:
			sample_results = []
		else:
			sample_results = [random.choice(qry_returned)]
		headers = [tup[0] for tup in crsr.description]

		if len(qry_returned) == 0:
			should_dump = True
		qry_formatted = format_query_to_spider(np, qrynp, database_name, sample=sample_results, headers=headers)
		try:
			sel = qry_formatted['sql']['orderBy']
			string = json.dumps(sel)
		except Exception as e:
			print(e)
			raise
		if should_dump:
			dumped_results.append(qry_formatted)
			dumped_gold_fp.write(qrynp.z + '\n')
			dumped_gold.append(qrynp.z + '\t' + database_name)
			dumped_canonical_fp.write(qrynp.c_english + '\n\n')
			dumped_canonical.append('In database ' + database_name + ': ' + qrynp.c_english)
		else:
			saved_results.append(qry_formatted)
			saved_gold_fp.write(qrynp.z + '\n')
			saved_gold.append(qrynp.z + '\t' + database_name)
			saved_canonical_fp.write(qrynp.c_english + '\n\n')
			saved_canonical.append('In database ' + database_name + ': ' + qrynp.c_english)
	crsr.close()
	conn.close()
	saved_path = SAVE_PATH + database_name + '/qrys_saved.json'
	dumped_path = SAVE_PATH + database_name + '/qrys_dumped.json'

	with open(saved_path, 'w') as fp:
		json.dump(saved_results, fp, indent=4)

	with open(dumped_path, 'w') as fp:
		json.dump(saved_results, fp, indent=4)

	saved_gold_fp.close()
	dumped_gold_fp.close()
	saved_canonical_fp.close()
	dumped_canonical_fp.close()
	error_logfile.close()
	print("finished generating {0} query entries from database $ {1} $".format(num_queries, database_name))
	return saved_results, dumped_results, saved_gold, dumped_gold, saved_canonical, dumped_canonical


def main(idx):
	# generate queries for English
	if idx in db_ids_to_ignore:
		print("database number %d ignored!" % idx)
	print("began generating query entries for database $ {0} $".format(idx))
	res_saved, res_dumped, gold_saved, gold_dumped, canonical_saved, canonical_dumped = generate_queries(idx)
	with open(SAVE_PATH + 'gold_saved.sql', 'a') as fp:
		for line in gold_saved:
			fp.write(line + '\n')
	with open(SAVE_PATH + 'gold_dumped.sql', 'a') as fp:
		for line in gold_dumped:
			fp.write(line + '\n')
	with open(SAVE_PATH + 'canonical_saved.txt', 'a') as fp:
		for line in canonical_saved:
			fp.write(line + '\n\n')
	with open(SAVE_PATH + 'canonical_dumped.txt', 'a') as fp:
		for line in canonical_dumped:
			fp.write(line + '\n\n')

	# here use 'a' in order to be able to create this file at the first run
	try:
		with open(SAVE_PATH + 'qrys_saved.json', 'r') as fp:
			f = json.load(fp)
			assert isinstance(f, list)
			f += res_saved
	except Exception as e:
		print('Exception at saved: ', e)
		f = res_saved
	with open(SAVE_PATH + 'qrys_saved.json', 'w') as fp:
		json.dump(f, fp, indent=4)
	try:
		with open(SAVE_PATH + 'qrys_dumped.json', 'r') as fp:
			f = json.load(fp)
			assert isinstance(f, list)
			f += res_dumped
	except Exception as e:
		print('Exception at dumped: ', e)
		f = res_dumped
	with open(SAVE_PATH + 'qrys_dumped.json', 'w') as fp:
		json.dump(f, fp, indent=4)


def debug():
	database_path, database_name, tnps, pnps, type_m, property_m, prop_r, valid, conn, crsr, num_queries = build_spider_dataset(51)
	assert valid
	fp = open('./result_0131.jsonl', 'w')
	for i in range(ITR_TRY):
		np, qrynp = scratch_build(tnps, pnps, type_m, property_m, prop_r, finalize_sequence=True, cursor=crsr, print_verbose=True)

		print('SQL: ', qrynp.z)
		print("Full question: ", qrynp.c_chinese)
		for item in qrynp.c_english_sequence:
			print(item)
		print("")
		fp.write(qrynp.z + '\n')
		try:
			res = crsr.execute(qrynp.z).fetchall()
			headers = [tup[0] for tup in crsr.description]
		except Exception as e:
			print(qrynp.z)
			print(e)
			raise
		qry_formatted = format_query_to_spider(np, qrynp, database_name, sample=res[:3], headers=headers)
	crsr.close()
	conn.close()
	fp.close()


if __name__ == '__main__':
	idx = args.db_id
	main(idx)
	# debug()
