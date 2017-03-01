# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
r"""Computes a header file to be used with SELECTIVE_REGISTRATION.

See the executable wrapper, print_selective_registration_header.py, for more
information.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys

from google.protobuf import text_format

from tensorflow.core.framework import graph_pb2
from tensorflow.python import pywrap_tensorflow
from tensorflow.python.platform import gfile
from tensorflow.python.platform import tf_logging


def get_ops_and_kernels(proto_fileformat, proto_files, default_ops_str):
  """Gets the ops and kernels needed from the model files."""
  ops = set()

  for proto_file in proto_files:
    tf_logging.info('Loading proto file %s', proto_file)
    # Load GraphDef.
    file_data = gfile.GFile(proto_file, 'rb').read()
    if proto_fileformat == 'rawproto':
      graph_def = graph_pb2.GraphDef.FromString(file_data)
    else:
      assert proto_fileformat == 'textproto'
      graph_def = text_format.Parse(file_data, graph_pb2.GraphDef())

    # Find all ops and kernels used by the graph.
    for node_def in graph_def.node:
      if not node_def.device:
        node_def.device = '/cpu:0'
      kernel_class = pywrap_tensorflow.TryFindKernelClass(
          node_def.SerializeToString())
      if kernel_class:
        op_and_kernel = (str(node_def.op), kernel_class.decode('utf-8'))
        if op_and_kernel not in ops:
          ops.add(op_and_kernel)
      else:
        print(
            'Warning: no kernel found for op %s' % node_def.op, file=sys.stderr)

  # Add default ops.
  if default_ops_str and default_ops_str != 'all':
    for s in default_ops_str.split(','):
      op, kernel = s.split(':')
      op_and_kernel = (op, kernel)
      if op_and_kernel not in ops:
        ops.add(op_and_kernel)

  return list(sorted(ops))


def get_header_from_ops_and_kernels(ops_and_kernels,
                                    include_all_ops_and_kernels):
  """Returns a header for use with tensorflow SELECTIVE_REGISTRATION.

  Args:
    ops_and_kernels: a set of (op_name, kernel_class_name) pairs to include.
    include_all_ops_and_kernels: if True, ops_and_kernels is ignored and all op
    kernels are included.

  Returns:
    the string of the header that should be written as ops_to_register.h.
  """
  ops = set([op for op, _ in ops_and_kernels])
  result_list = []

  def append(s):
    result_list.append(s)

  append('#ifndef OPS_TO_REGISTER')
  append('#define OPS_TO_REGISTER')

  if include_all_ops_and_kernels:
    append('#define SHOULD_REGISTER_OP(op) true')
    append('#define SHOULD_REGISTER_OP_KERNEL(clz) true')
    append('#define SHOULD_REGISTER_OP_GRADIENT true')
  else:
    append('constexpr inline bool ShouldRegisterOp(const char op[]) {')
    append('  return false')
    for op in sorted(ops):
      append('     || (strcmp(op, "%s") == 0)' % op)
    append('  ;')
    append('}')
    append('#define SHOULD_REGISTER_OP(op) ShouldRegisterOp(op)')
    append('')

    line = 'const char kNecessaryOpKernelClasses[] = ","\n'
    for _, kernel_class in ops_and_kernels:
      line += '"%s,"\n' % kernel_class
    line += ';'
    append(line)
    append('#define SHOULD_REGISTER_OP_KERNEL(clz) '
           '(strstr(kNecessaryOpKernelClasses, "," clz ",") != nullptr)')
    append('')

    append('#define SHOULD_REGISTER_OP_GRADIENT ' + (
        'true' if 'SymbolicGradient' in ops else 'false'))

  append('#endif')
  return '\n'.join(result_list)


def get_header(graphs,
               proto_fileformat='rawproto',
               default_ops='NoOp:NoOp,_Recv:RecvOp,_Send:SendOp'):
  """Computes a header for use with tensorflow SELECTIVE_REGISTRATION.

  Args:
    graphs: a list of paths to GraphDef files to include.
    proto_fileformat: optional format of proto file, either 'textproto' or
      'rawproto' (default).
    default_ops: optional comma-separated string of operator:kernel pairs to
      always include implementation for. Pass 'all' to have all operators and
      kernels included. Default: 'NoOp:NoOp,_Recv:RecvOp,_Send:SendOp'.
  Returns:
    the string of the header that should be written as ops_to_register.h.
  """
  ops_and_kernels = get_ops_and_kernels(proto_fileformat, graphs, default_ops)
  if not ops_and_kernels:
    print('Error reading graph!')
    return 1

  return get_header_from_ops_and_kernels(ops_and_kernels, default_ops == 'all')