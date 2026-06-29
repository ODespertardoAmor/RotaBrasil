// ==========================================
// CONFIGURAÇÃO PARA RENDER.COM
// ==========================================

// 🔥 ALTERE ESTA URL PARA A DO SEU BACKEND NO RENDER
const API_BASE = 'https://rotabrasil-tobu.onrender.com'; // Substitua pela sua URL

// Ou use esta configuração para detectar automaticamente
// const API_BASE = window.location.hostname === 'localhost' 
//     ? 'http://localhost:5000' 
//     : 'https://seu-backend.onrender.com';

// Token de autenticação
const token = localStorage.getItem('token') || '';

// Headers padrão para requisições
const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
};

// ==========================================
// INICIALIZAÇÃO
// ==========================================
document.addEventListener('DOMContentLoaded', function() {
    // Verificar se está logado
    if (!token) {
        // Redirecionar para login ou mostrar mensagem
        console.warn('Usuário não autenticado');
        // window.location.href = '/login';
    }

    // Toggle sidebar
    const toggleBtn = document.getElementById('toggleSidebar');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
            document.getElementById('sidebar').classList.toggle('collapsed');
            document.getElementById('mainContent').classList.toggle('expanded');
        });
    }

    // Navegação
    document.querySelectorAll('.sidebar .nav-link[data-section]').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const section = this.dataset.section;
            showSection(section);
            
            // Atualizar active
            document.querySelectorAll('.sidebar .nav-link[data-section]').forEach(l => l.classList.remove('active'));
            this.classList.add('active');
        });
    });

    // Carregar dados iniciais
    carregarDashboard();
    carregarMotoristas();
    carregarPassageiros();
    carregarUsuarios();
    carregarCorridas();
    carregarAvaliacoes();
    carregarTransacoes();
    carregarCarteiras();

    // Atualizar a cada 30 segundos
    setInterval(() => {
        carregarDashboard();
        carregarMotoristas();
        carregarPassageiros();
        carregarUsuarios();
    }, 30000);
});

// ==========================================
// FUNÇÕES DE CARREGAMENTO
// ==========================================

// Mostrar seção
function showSection(section) {
    document.querySelectorAll('.section-content').forEach(el => el.classList.remove('active'));
    const target = document.getElementById(`section-${section}`);
    if (target) target.classList.add('active');
}

// ==================== DASHBOARD ====================
async function carregarDashboard() {
    try {
        const response = await fetch(`${API_BASE}/admin/dashboard2`, { 
            headers,
            credentials: 'include'
        });
        
        if (response.status === 401) {
            // Token expirado ou inválido
            localStorage.removeItem('token');
            window.location.href = '/login';
            return;
        }
        
        if (!response.ok) throw new Error('Erro ao carregar dashboard');
        
        const data = await response.json();
        
        document.getElementById('totalUsuarios').textContent = data.usuarios || 0;
        document.getElementById('motoristasOnline').textContent = data.motoristas_online || 0;
        document.getElementById('corridasHoje').textContent = data.corridas || 0;
        document.getElementById('saldoTotal').textContent = `R$ ${(data.saldo_total || 0).toFixed(2).replace('.', ',')}`;
        document.getElementById('onlineCount').textContent = `${data.motoristas_online || 0} online`;
        
        // Carregar corridas recentes
        await carregarCorridasRecentes();
        await carregarUltimasAvaliacoes();
        
    } catch (error) {
        console.error('Erro ao carregar dashboard:', error);
        mostrarToast('Erro ao carregar dados do dashboard', 'danger');
    }
}

async function carregarCorridasRecentes() {
    try {
        const response = await fetch(`${API_BASE}/admin/corridas/recentes`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar corridas recentes');
        
        const data = await response.json();
        const tbody = document.getElementById('corridasRecentes');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center">Nenhuma corrida recente</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.slice(0, 10).map(c => `
            <tr>
                <td>#${c.id}</td>
                <td>${c.passageiro_nome || 'N/A'}</td>
                <td>${c.motorista_nome || 'N/A'}</td>
                <td>R$ ${(c.valor || 0).toFixed(2).replace('.', ',')}</td>
                <td><span class="badge-status ${c.status}">${c.status}</span></td>
                <td>${c.data_criacao ? new Date(c.data_criacao).toLocaleDateString('pt-BR') : ''}</td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar corridas recentes:', error);
    }
}

async function carregarUltimasAvaliacoes() {
    try {
        const response = await fetch(`${API_BASE}/admin/avaliacoes`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar avaliações');
        
        const data = await response.json();
        const container = document.getElementById('ultimasAvaliacoes');
        
        if (!data.length) {
            container.innerHTML = '<p class="text-muted text-center">Nenhuma avaliação recente</p>';
            return;
        }
        
        container.innerHTML = data.slice(0, 5).map(a => `
            <div class="d-flex align-items-center mb-2 pb-2 border-bottom">
                <div class="flex-grow-1">
                    <div class="fw-bold">${a.avaliador || 'Anônimo'}</div>
                    <div class="stars">${'★'.repeat(a.nota)}${'☆'.repeat(5 - a.nota)}</div>
                    <small class="text-muted">${a.comentario || 'Sem comentário'}</small>
                </div>
                <span class="badge bg-${a.nota >= 4 ? 'success' : a.nota >= 3 ? 'warning' : 'danger'}">${a.nota}</span>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar últimas avaliações:', error);
    }
}

// ==================== USUÁRIOS ====================
async function carregarUsuarios() {
    try {
        const response = await fetch(`${API_BASE}/admin/usuarios`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar usuários');
        
        const data = await response.json();
        const tbody = document.getElementById('listaUsuarios');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">Nenhum usuário encontrado</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(u => `
            <tr>
                <td>#${u.id}</td>
                <td>
                    ${u.foto_perfil ? `<img src="${u.foto_perfil}" class="avatar-sm me-2">` : ''}
                    ${u.nome}
                </td>
                <td>${u.email}</td>
                <td><span class="badge bg-${u.tipo === 'motorista' ? 'primary' : 'secondary'}">${u.tipo}</span></td>
                <td>${u.telefone || 'N/A'}</td>
                <td><span class="badge-status ${u.online ? 'online' : 'offline'}">${u.online ? 'Online' : 'Offline'}</span></td>
                <td>
                    <button class="btn btn-info btn-sm btn-icon" onclick="verUsuario(${u.id})" title="Ver">
                        <i class="bi bi-eye"></i>
                    </button>
                    <button class="btn btn-danger btn-sm btn-icon" onclick="excluirUsuario(${u.id})" title="Excluir">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar usuários:', error);
        document.getElementById('listaUsuarios').innerHTML = '<tr><td colspan="7" class="text-center text-danger">Erro ao carregar dados</td></tr>';
    }
}

// ==================== MOTORISTAS ====================
async function carregarMotoristas() {
    try {
        const response = await fetch(`${API_BASE}/admin/motoristas`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar motoristas');
        
        const data = await response.json();
        const tbody = document.getElementById('listaMotoristas');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">Nenhum motorista encontrado</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(m => `
            <tr>
                <td>#${m.id}</td>
                <td>
                    ${m.foto_perfil ? `<img src="${m.foto_perfil}" class="avatar-sm me-2">` : ''}
                    ${m.nome}
                </td>
                <td>${m.email}</td>
                <td>${m.carro || 'N/A'}</td>
                <td>${m.placa || 'N/A'}</td>
                <td><span class="badge-status ${m.online ? 'online' : 'offline'}">${m.online ? 'Online' : 'Offline'}</span></td>
                <td>
                    <button class="btn btn-info btn-sm btn-icon" onclick="verMotorista(${m.id})" title="Ver">
                        <i class="bi bi-eye"></i>
                    </button>
                    <button class="btn btn-danger btn-sm btn-icon" onclick="excluirMotorista(${m.id})" title="Excluir">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar motoristas:', error);
        document.getElementById('listaMotoristas').innerHTML = '<tr><td colspan="7" class="text-center text-danger">Erro ao carregar dados</td></tr>';
    }
}

// ==================== PASSAGEIROS ====================
async function carregarPassageiros() {
    try {
        const response = await fetch(`${API_BASE}/admin/passageiros`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar passageiros');
        
        const data = await response.json();
        const tbody = document.getElementById('listaPassageiros');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center">Nenhum passageiro encontrado</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(p => `
            <tr>
                <td>#${p.id}</td>
                <td>
                    ${p.foto_perfil ? `<img src="${p.foto_perfil}" class="avatar-sm me-2">` : ''}
                    ${p.nome}
                </td>
                <td>${p.email}</td>
                <td>${p.telefone || 'N/A'}</td>
                <td>${p.foto_perfil ? '<i class="bi bi-check-circle text-success"></i>' : '<i class="bi bi-x-circle text-danger"></i>'}</td>
                <td>
                    <button class="btn btn-info btn-sm btn-icon" onclick="verPassageiro(${p.id})" title="Ver">
                        <i class="bi bi-eye"></i>
                    </button>
                    <button class="btn btn-danger btn-sm btn-icon" onclick="excluirPassageiro(${p.id})" title="Excluir">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar passageiros:', error);
        document.getElementById('listaPassageiros').innerHTML = '<tr><td colspan="6" class="text-center text-danger">Erro ao carregar dados</td></tr>';
    }
}

// ==================== CORRIDAS ====================
async function carregarCorridas() {
    try {
        const response = await fetch(`${API_BASE}/admin/corridas`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar corridas');
        
        const data = await response.json();
        const tbody = document.getElementById('listaCorridas');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">Nenhuma corrida encontrada</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(c => `
            <tr>
                <td>#${c.id}</td>
                <td>${c.passageiro_nome || 'N/A'}</td>
                <td>${c.motorista_nome || 'N/A'}</td>
                <td>${c.origem || 'N/A'}</td>
                <td>${c.destino || 'N/A'}</td>
                <td>R$ ${(c.valor || 0).toFixed(2).replace('.', ',')}</td>
                <td><span class="badge-status ${c.status}">${c.status}</span></td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar corridas:', error);
        document.getElementById('listaCorridas').innerHTML = '<tr><td colspan="7" class="text-center text-danger">Erro ao carregar dados</td></tr>';
    }
}

// ==================== AVALIAÇÕES ====================
async function carregarAvaliacoes() {
    try {
        const response = await fetch(`${API_BASE}/admin/avaliacoes`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar avaliações');
        
        const data = await response.json();
        const tbody = document.getElementById('listaAvaliacoes');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center">Nenhuma avaliação encontrada</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(a => `
            <tr>
                <td>#${a.id}</td>
                <td>${a.corrida_id || 'N/A'}</td>
                <td>${a.avaliador || 'N/A'}</td>
                <td>${a.avaliado || 'N/A'}</td>
                <td>
                    <span class="stars">${'★'.repeat(a.nota)}${'☆'.repeat(5 - a.nota)}</span>
                    <span class="badge bg-${a.nota >= 4 ? 'success' : a.nota >= 3 ? 'warning' : 'danger'}">${a.nota}</span>
                </td>
                <td>${a.comentario || 'Sem comentário'}</td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar avaliações:', error);
        document.getElementById('listaAvaliacoes').innerHTML = '<tr><td colspan="6" class="text-center text-danger">Erro ao carregar dados</td></tr>';
    }
}

// ==================== TRANSAÇÕES ====================
async function carregarTransacoes() {
    try {
        const response = await fetch(`${API_BASE}/transacoes`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar transações');
        
        const data = await response.json();
        const tbody = document.getElementById('listaTransacoes');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center">Nenhuma transação encontrada</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(t => `
            <tr>
                <td>#${t.id}</td>
                <td>Usuário ${t.usuario_id}</td>
                <td><span class="badge bg-${t.tipo === 'credito' ? 'success' : 'danger'}">${t.tipo}</span></td>
                <td class="${t.tipo === 'credito' ? 'text-success' : 'text-danger'}">${t.tipo === 'credito' ? '+' : '-'} R$ ${(t.valor || 0).toFixed(2).replace('.', ',')}</td>
                <td>${t.descricao || 'N/A'}</td>
                <td>${t.data || 'N/A'}</td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar transações:', error);
        document.getElementById('listaTransacoes').innerHTML = '<tr><td colspan="6" class="text-center text-danger">Erro ao carregar dados</td></tr>';
    }
}

// ==================== CARTEIRAS ====================
async function carregarCarteiras() {
    try {
        const response = await fetch(`${API_BASE}/admin/carteiras`, { headers });
        if (!response.ok) throw new Error('Erro ao carregar carteiras');
        
        const data = await response.json();
        const tbody = document.getElementById('listaCarteiras');
        
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center">Nenhuma carteira encontrada</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(c => `
            <tr>
                <td>#${c.id}</td>
                <td>Usuário ${c.usuario_id}</td>
                <td class="text-success">R$ ${(c.saldo || 0).toFixed(2).replace('.', ',')}</td>
                <td class="text-warning">R$ ${(c.saldo_bloqueado || 0).toFixed(2).replace('.', ',')}</td>
                <td>${c.criado_em || 'N/A'}</td>
            </tr>
        `).join('');
        
    } catch (error) {
        console.error('Erro ao carregar carteiras:', error);
        document.getElementById('listaCarteiras').innerHTML = '<tr><td colspan="5" class="text-center text-danger">Erro ao carregar dados</td></tr>';
    }
}

// ==================== AÇÕES CRUD ====================

// Excluir usuário
async function excluirUsuario(id) {
    if (!confirm(`Tem certeza que deseja excluir o usuário #${id}? Esta ação não pode ser desfeita.`)) return;
    
    try {
        const response = await fetch(`${API_BASE}/admin/excluir_usuario/${id}`, {
            method: 'DELETE',
            headers
        });
        
        if (!response.ok) throw new Error('Erro ao excluir usuário');
        
        mostrarToast('Usuário excluído com sucesso!', 'success');
        carregarUsuarios();
        carregarDashboard();
        
    } catch (error) {
        console.error('Erro ao excluir usuário:', error);
        mostrarToast('Erro ao excluir usuário', 'danger');
    }
}

// Excluir motorista
async function excluirMotorista(id) {
    if (!confirm(`Tem certeza que deseja excluir o motorista #${id}? Esta ação não pode ser desfeita.`)) return;
    
    try {
        const response = await fetch(`${API_BASE}/admin/excluir_motorista/${id}`, {
            method: 'DELETE',
            headers
        });
        
        if (!response.ok) throw new Error('Erro ao excluir motorista');
        
        mostrarToast('Motorista excluído com sucesso!', 'success');
        carregarMotoristas();
        carregarDashboard();
        
    } catch (error) {
        console.error('Erro ao excluir motorista:', error);
        mostrarToast('Erro ao excluir motorista', 'danger');
    }
}

// Excluir passageiro
async function excluirPassageiro(id) {
    if (!confirm(`Tem certeza que deseja excluir o passageiro #${id}? Esta ação não pode ser desfeita.`)) return;
    
    try {
        const response = await fetch(`${API_BASE}/admin/excluir_passageiro/${id}`, {
            method: 'DELETE',
            headers
        });
        
        if (!response.ok) throw new Error('Erro ao excluir passageiro');
        
        mostrarToast('Passageiro excluído com sucesso!', 'success');
        carregarPassageiros();
        carregarDashboard();
        
    } catch (error) {
        console.error('Erro ao excluir passageiro:', error);
        mostrarToast('Erro ao excluir passageiro', 'danger');
    }
}

// ==================== TOAST NOTIFICATIONS ====================
function mostrarToast(mensagem, tipo = 'success') {
    const container = document.getElementById('toastContainer') || criarToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${tipo} border-0 show`;
    toast.role = 'alert';
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${mensagem}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

function criarToastContainer() {
    const container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    document.body.appendChild(container);
    return container;
}

// ==================== BUSCA ====================
document.getElementById('searchUsuarios')?.addEventListener('keyup', function() {
    const searchTerm = this.value.toLowerCase();
    const rows = document.querySelectorAll('#tabelaUsuarios tbody tr');
    
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
});

// ==================== EXPORTAR DADOS ====================
function exportarCSV(tabelaId, nomeArquivo = 'dados.csv') {
    const table = document.getElementById(tabelaId);
    if (!table) return;
    
    let csv = '';
    const rows = table.querySelectorAll('tr');
    
    rows.forEach(row => {
        const cols = row.querySelectorAll('td, th');
        const rowData = [];
        cols.forEach(col => {
            let text = col.textContent.trim();
            text = text.replace(/,/g, ';');
            rowData.push(text);
        });
        csv += rowData.join(',') + '\n';
    });
    
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = nomeArquivo;
    a.click();
    window.URL.revokeObjectURL(url);
}

// Adicionar botões de exportação
document.querySelectorAll('.section-content').forEach(section => {
    const tabela = section.querySelector('.table');
    if (tabela) {
        const header = section.querySelector('h5');
        if (header) {
            const btnExport = document.createElement('button');
            btnExport.className = 'btn btn-outline-secondary btn-sm float-end';
            btnExport.innerHTML = '<i class="bi bi-download"></i> Exportar CSV';
            btnExport.onclick = () => exportarCSV(tabela.id || 'tabela', `${section.id}.csv`);
            header.parentElement?.appendChild(btnExport);
        }
    }
});

// ==================== VERIFICAÇÃO DE CONEXÃO ====================
async function verificarConexao() {
    try {
        const response = await fetch(`${API_BASE}/teste`, { 
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (response.ok) {
            console.log('✅ Conectado ao backend em:', API_BASE);
            return true;
        } else {
            console.error('❌ Erro ao conectar ao backend:', response.status);
            return false;
        }
    } catch (error) {
        console.error('❌ Erro de conexão:', error);
        mostrarToast('Erro de conexão com o servidor', 'danger');
        return false;
    }
}

// Verificar conexão ao carregar
verificarConexao();

// ==========================================
// FUNÇÕES DE VISUALIZAÇÃO (EM DESENVOLVIMENTO)
// ==========================================

function verUsuario(id) {
    // Implementar modal de visualização
    mostrarToast(`Visualizando usuário #${id}`, 'info');
}

function verMotorista(id) {
    mostrarToast(`Visualizando motorista #${id}`, 'info');
}

function verPassageiro(id) {
    mostrarToast(`Visualizando passageiro #${id}`, 'info');
}
