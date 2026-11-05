// Handwritten body; Waveflow generates the top-level interface around this file.
#pragma once

namespace maxpool_impl {

template <int BW>
static void emit(hls::stream<streamutils::axi4s_word<BW>>& output,
                 ap_uint<32> data, bool last) {
#pragma HLS INLINE
    streamutils::axi4s_word<BW> word;
    word.data = data;
    word.keep = -1;
    word.strb = -1;
    word.last = last;
    output.write(word);
}

static void fail(ap_uint<1>& halted, ap_uint<32>& error,
                 ap_uint<32>& error_tx_id, unsigned code, ap_uint<32> tx) {
#pragma HLS INLINE
    halted = 1;
    error = code;
    error_tx_id = tx;
}

template <int in_bw, int out_bw>
void body(hls::stream<streamutils::axi4s_word<in_bw>>& s_in,
          hls::stream<streamutils::axi4s_word<out_bw>>& m_out,
          ap_uint<1>& halted, ap_uint<32>& error, ap_uint<32>& error_tx_id) {
#pragma HLS INLINE
    static_assert(in_bw == 32 && out_bw == 32, "This protocol uses 32-bit beats");
    // Sixteen independent banks permit a complete 4x4 window to be read together.
    // A COMPUTE fully overwrites its image region before any response is emitted.
    ap_int<16> image[64][64];
#pragma HLS ARRAY_PARTITION variable=image cyclic factor=4 dim=1
#pragma HLS ARRAY_PARTITION variable=image cyclic factor=4 dim=2
    halted = 0;
    error = 0;
    error_tx_id = 0;

    while (true) {
        ap_uint<32> header[4];
#pragma HLS ARRAY_PARTITION variable=header complete
    read_header:
        for (int i = 0; i < 4; ++i) {
            streamutils::axi4s_word<in_bw> word = s_in.read();
            header[i] = word.data;
            if (bool(word.last) != (i == 3)) {
                fail(halted, error, error_tx_id, 1, header[0]);
                return;
            }
        }
        const ap_uint<32> tx = header[0];
        const ap_uint<32> opcode = header[1];
        if (opcode == 0) return;  // END ignores every COMPUTE-only field.
        if (opcode != 1) {
            fail(halted, error, error_tx_id, 2, tx);
            return;
        }
        const unsigned h = header[2].range(15, 0).to_uint();
        const unsigned w = header[2].range(31, 16).to_uint();
        const unsigned k = header[3].to_uint();
        // Check full encoded values before narrowing them or reading any payload.
        if (h < 2 || h > 64 || w < 2 || w > 64 || (k != 2 && k != 4)
            || k > h || k > w || (h & (k - 1)) != 0 || (w & (k - 1)) != 0) {
            fail(halted, error, error_tx_id, 3, tx);
            return;
        }
        const bool k4 = k == 4;
        const unsigned nsamples = h * w;
        ap_uint<7> row = 0, col = 0;
    buffer_image:
        for (unsigned n = 0; n < nsamples; ++n) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=4 max=4096
            streamutils::axi4s_word<in_bw> word = s_in.read();
            const bool final = n + 1 == nsamples;
            image[row][col] = ap_int<16>(word.data.range(15, 0));
            if (bool(word.last) != final) {
                fail(halted, error, error_tx_id, final ? 5 : 4, tx);
                return;
            }
            if (col + 1 == w) { col = 0; ++row; }
            else ++col;
        }

        const unsigned oh = k4 ? h >> 2 : h >> 1;
        const unsigned ow = k4 ? w >> 2 : w >> 1;
        emit(m_out, tx, false);
        emit(m_out, ap_uint<32>((ow << 16) | oh), true);
        ap_uint<7> base_r = 0, base_c = 0;
        const unsigned nout = oh * ow;
    emit_windows:
        for (unsigned n = 0; n < nout; ++n) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=1024
            ap_int<16> v[16];
#pragma HLS ARRAY_PARTITION variable=v complete
            for (int dr = 0; dr < 4; ++dr) {
#pragma HLS UNROLL
                for (int dc = 0; dc < 4; ++dc) {
#pragma HLS UNROLL
                    v[dr * 4 + dc] = (k4 || (dr < 2 && dc < 2))
                        ? image[base_r + dr][base_c + dc] : ap_int<16>(-32768);
                }
            }
            // Balanced signed reduction; no arithmetic changes sample values.
            for (int j = 0; j < 8; ++j) {
#pragma HLS UNROLL
                v[j] = v[j] > v[j + 8] ? v[j] : v[j + 8];
            }
            for (int j = 0; j < 4; ++j) {
#pragma HLS UNROLL
                v[j] = v[j] > v[j + 4] ? v[j] : v[j + 4];
            }
            for (int j = 0; j < 2; ++j) {
#pragma HLS UNROLL
                v[j] = v[j] > v[j + 2] ? v[j] : v[j + 2];
            }
            v[0] = v[0] > v[1] ? v[0] : v[1];
            ap_uint<32> bits = 0;
            bits.range(15, 0) = v[0].range(15, 0);
            emit(m_out, bits, n + 1 == nout);
            if (base_c + k == w) { base_c = 0; base_r += k; }
            else base_c += k;
        }
    }
}
} // namespace maxpool_impl
