#include "maxpool.hpp"

void maxpool(
    hls::stream<streamutils::axi4s_word<32>>& s_in,
    hls::stream<streamutils::axi4s_word<32>>& m_out,
    ap_uint<1>& halted,
    ap_uint<32>& error,
    ap_uint<32>& error_tx_id
) {
#pragma HLS INTERFACE axis port=s_in register_mode=off
#pragma HLS INTERFACE axis port=m_out
#pragma HLS INTERFACE s_axilite port=halted       bundle=control
#pragma HLS INTERFACE s_axilite port=error        bundle=control
#pragma HLS INTERFACE s_axilite port=error_tx_id  bundle=control
#pragma HLS INTERFACE s_axilite port=return       bundle=control
    maxpool_impl::body(s_in, m_out, halted, error, error_tx_id);
}

